"""Shared Prometheus metrics — one registry, reused by api/ai/worker/mcp.

Mirrors ``ekoa_config.logging``'s "one shared setup, per-service labels"
approach: a single set of metric definitions here, labeled by ``service`` at
record time, rather than each service inventing its own metric names. The
specific counters (connector sync, AI chat latency) directly reuse the same
numbers Phase 10/12's Locust baselines measured manually — see
``docs/performance-and-nfrs.md`` — so this is now queryable instead of a
one-off benchmark run.
"""

from __future__ import annotations

import time
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUEST_COUNT = Counter(
    "ekoa_http_requests_total",
    "Total HTTP requests handled",
    ["service", "method", "path", "status"],
)

HTTP_REQUEST_LATENCY = Histogram(
    "ekoa_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["service", "method", "path"],
)

CONNECTOR_SYNC_COUNT = Counter(
    "ekoa_connector_sync_total",
    "Connector sync task outcomes",
    ["provider", "status"],  # status: success | failed
)

WORKFLOW_RUN_COUNT = Counter(
    "ekoa_workflow_run_total",
    "Workflow run outcomes",
    ["template_id", "status"],
)

AI_CHAT_LATENCY = Histogram(
    "ekoa_ai_chat_latency_seconds",
    "End-to-end AI chat turn latency in seconds",
    ["degraded"],
    buckets=(0.5, 1, 2, 3, 5, 8, 13, 21, 34, 55),
)


def metrics_response() -> tuple[bytes, str]:
    """Return (body, content_type) for a /metrics route."""
    return generate_latest(), CONTENT_TYPE_LATEST


class PrometheusMiddleware:
    """Raw-ASGI middleware recording request count + latency per route.

    Same shape as :class:`ekoa_config.logging.CorrelationIdMiddleware`
    (raw ASGI, not Starlette's ``BaseHTTPMiddleware``) so it composes
    identically in each service's middleware stack. ``scope["route"].path``
    (the matched route template, e.g. ``/api/v1/documents/{document_id}``)
    is used instead of the raw path when available, so metrics don't
    cardinality-explode on path parameters like UUIDs.
    """

    def __init__(self, app: Any, service: str):
        self.app = app
        self.service = service

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            path = getattr(route, "path", None) or scope.get("path", "unknown")
            duration = time.perf_counter() - start
            HTTP_REQUEST_COUNT.labels(
                service=self.service, method=method, path=path, status=str(status_code)
            ).inc()
            HTTP_REQUEST_LATENCY.labels(
                service=self.service, method=method, path=path
            ).observe(duration)
