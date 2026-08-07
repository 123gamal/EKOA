"""Lightweight in-memory sliding-window rate limiting shared by the API and AI services.

Per-process and thread-safe, keyed by ``scope + client_key`` (client IP by
default; a caller may supply a custom key function, e.g. an authenticated user
id). Suitable for single-replica deployments; a distributed backend such as
Redis can replace :class:`RateLimiter` later without changing call sites.

Two enforcement points:

- :func:`RateLimitMiddleware` applies the general default limit (per IP) to
  every HTTP request, so nothing is unbounded by default.
- :func:`rate_limit` is a FastAPI dependency factory for tighter per-route
  limits (e.g. ``/auth/login``), which are the brute-force/spam targets.

Rejections are logged through the Phase 2 structured JSON logger with the
``rate_limit`` logger name so they are visible in the same correlation-ID
stream, and every rejection returns 429 with a ``Retry-After`` header.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from ekoa_config.logging import get_logger
from ekoa_config.settings import get_settings


class RateLimiter:
    """Sliding-window counter keyed by ``(scope, client_key)``.

    Only *allowed* requests are recorded. A rejected client therefore stays
    rejected until the oldest recorded timestamp slides out of the window, at
    which point the next attempt is permitted again.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, scope: str, key: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        """Record one attempt; return ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets[(scope, key)]
            while bucket and now - bucket[0] > window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = int(window_seconds - (now - bucket[0])) + 1
                return False, max(retry_after, 1)
            bucket.append(now)
            return True, 0

    def reset(self) -> None:
        """Clear all buckets (used by tests between cases)."""
        with self._lock:
            self._buckets.clear()


_limiter = RateLimiter()
_logger = get_logger("rate_limit")


def get_rate_limiter() -> RateLimiter:
    """Return the process-wide rate limiter singleton."""
    return _limiter


def _client_key(request: Request) -> str:
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


class RateLimitExceeded(HTTPException):
    """429 response carrying a ``Retry-After`` header."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please retry later.",
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(
    scope: str,
    limit: int,
    window_seconds: int = 60,
    *,
    key_func: Callable[[Request], str] | None = None,
) -> Callable[[Request], None]:
    """FastAPI dependency factory enforcing a per-client limit.

    Usage: ``Depends(rate_limit("auth:login", 10, 60))``
    """

    def _dependency(request: Request) -> None:
        key = key_func(request) if key_func is not None else _client_key(request)
        allowed, retry_after = get_rate_limiter().check(scope, key, limit, window_seconds)
        if not allowed:
            _logger.warning(
                "rate_limit_exceeded",
                extra={
                    "scope": scope,
                    "limit": limit,
                    "window_seconds": window_seconds,
                    "client_key": key,
                    "retry_after": retry_after,
                },
            )
            raise RateLimitExceeded(retry_after)

    return _dependency


def auth_login_limit() -> Callable[[Request], None]:
    """Tight per-IP limit for credential attempts."""
    settings = get_settings()
    return rate_limit("auth:login", settings.RATE_LIMIT_LOGIN_LIMIT, settings.RATE_LIMIT_DEFAULT_WINDOW_SECONDS)


def auth_register_limit() -> Callable[[Request], None]:
    """Tight per-IP limit for new-account creation (spam protection)."""
    settings = get_settings()
    return rate_limit("auth:register", settings.RATE_LIMIT_REGISTER_LIMIT, settings.RATE_LIMIT_DEFAULT_WINDOW_SECONDS)


def auth_refresh_limit() -> Callable[[Request], None]:
    """Moderately tight per-IP limit for refresh-token rotation."""
    settings = get_settings()
    return rate_limit("auth:refresh", settings.RATE_LIMIT_REFRESH_LIMIT, settings.RATE_LIMIT_DEFAULT_WINDOW_SECONDS)


class RateLimitMiddleware:
    """Applies the general default per-IP limit to every HTTP request.

    Health probes are exempt so Docker healthchecks are never rate-limited, and
    CORS ``OPTIONS`` preflights are not counted.
    """

    def __init__(
        self,
        app: Callable,
        *,
        exempt_paths: tuple[str, ...] = ("/health",),
        logger_name: str = "rate_limit",
    ) -> None:
        self.app = app
        self.exempt_paths = exempt_paths
        self.logger = get_logger(logger_name)

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("method") == "OPTIONS" or scope.get("path") in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        key = client[0] if client and client[0] else "unknown"

        settings = get_settings()
        allowed, retry_after = get_rate_limiter().check(
            "general",
            key,
            settings.RATE_LIMIT_DEFAULT_LIMIT,
            settings.RATE_LIMIT_DEFAULT_WINDOW_SECONDS,
        )

        if not allowed:
            self.logger.warning(
                "rate_limit_exceeded",
                extra={
                    "scope": "general",
                    "limit": settings.RATE_LIMIT_DEFAULT_LIMIT,
                    "window_seconds": settings.RATE_LIMIT_DEFAULT_WINDOW_SECONDS,
                    "client_key": key,
                    "retry_after": retry_after,
                },
            )
            response = JSONResponse(
                {"detail": "Too many requests. Please retry later."},
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
