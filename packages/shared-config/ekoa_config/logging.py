"""EKOA shared structured logging — JSON output with end-to-end correlation IDs.

Single logging setup shared by ``apps.api``, ``apps.ai``, and ``apps.worker`` so
every service emits the same JSON shape: timestamp, service name, level,
logger, message, and a ``correlation_id`` field. The correlation ID lives in a
``contextvars`` so any log line emitted while handling a request — or a Celery
task kicked off by that request — automatically carries the originating ID.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

# Correlation ID propagated via contextvars. Set by the ASGI middleware for
# HTTP requests and re-set inside Celery tasks from their task payload.
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)

_SERVICE_NAME = "ekoa"

# First call to ``setup_logging`` in a process wins. Several service modules
# import each other (the API lazily imports ``apps.worker.tasks``, which imports
# ``apps.worker.main``), so a later import-time ``setup_logging("worker")`` must
# not clobber the API process's already-configured JSON handler.
_CONFIGURED = False


def set_service_name(service: str) -> None:
    """Set the default ``service`` value for formatters created without one."""
    global _SERVICE_NAME
    _SERVICE_NAME = service


def get_correlation_id() -> str:
    """Return the current request/task correlation ID (empty when unset)."""
    return correlation_id_var.get()


# Standard LogRecord attributes. Anything else on a record is a structured
# field we want surfaced in the JSON payload.
_RESERVED_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def __init__(self, service: str | None = None) -> None:
        super().__init__()
        # Captured at construction so later ``setup_logging`` calls in the same
        # process (e.g. from an incidentally imported worker module) cannot
        # change the service name stamped by this handler.
        self._service = service or _SERVICE_NAME

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": self._service,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a logger wired to the shared JSON configuration."""
    return logging.getLogger(name)


def setup_logging(service: str, level: str = "INFO") -> None:
    """Configure the root logger once to emit JSON structured logs.

    Only the first call in a process takes effect (see ``_CONFIGURED``); the
    entrypoint module of each service calls this at startup. Uvicorn's own
    access log is disabled because the correlation middleware emits the JSON
    request line.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)


class CorrelationIdMiddleware:
    """ASGI middleware that assigns/reuses a correlation ID per request.

    - Reuses an inbound ``X-Request-ID`` header when present, otherwise
      generates a UUID.
    - Stores the ID in a ``contextvars`` so request-handler logs carry it.
    - Echoes it back on the response ``X-Request-ID`` header.
    - Logs one JSON request line (method, path, status, duration, correlation
      ID) per request.
    """

    def __init__(self, app: Any, logger_name: str = "http"):
        self.app = app
        self.logger = get_logger(logger_name)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        cid = headers.get("x-request-id") or str(uuid.uuid4())
        token = correlation_id_var.set(cid)

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers_list = list(message.get("headers", []))
                if not any(
                    k.decode("latin-1").lower() == "x-request-id"
                    for k, _ in headers_list
                ):
                    headers_list.append((b"x-request-id", cid.encode("latin-1")))
                message["headers"] = headers_list
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            self.logger.exception(
                "unhandled_request_error",
                extra={
                    "http_method": scope.get("method"),
                    "path": scope.get("path"),
                },
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self.logger.info(
                "request",
                extra={
                    "http_method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            correlation_id_var.reset(token)
