"""Sliding-window rate limiting shared by the API and AI services.

Two backends, selected by ``RATE_LIMIT_BACKEND`` (see :func:`get_rate_limiter`):

- :class:`RateLimiter` — per-process, in-memory, thread-safe. The default;
  used in tests and local dev without Docker. Does **not** share state across
  replicas/processes.
- :class:`RedisRateLimiter` — Redis sorted-set backed, shared across every
  process talking to the same Redis instance. Used by docker-compose for the
  api/ai services so limits are correct with more than one replica.

Both expose ``async def acheck(scope, key, limit, window_seconds) ->
(allowed, retry_after_seconds)`` as the common interface consumed by call
sites. ``RateLimiter`` additionally keeps its original **sync** ``check()``
for direct unit testing and backward compatibility.

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
from typing import Awaitable, Callable

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from ekoa_config.logging import get_logger
from ekoa_config.redis_client import get_async_redis
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

    async def acheck(self, scope: str, key: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        """Async-compatible wrapper around :meth:`check` (no real awaiting)."""
        return self.check(scope, key, limit, window_seconds)


class RedisRateLimiter:
    """Sliding-window counter backed by a Redis sorted set, shared across processes.

    Same "only allowed requests are recorded" semantics as :class:`RateLimiter`:
    each key ``rl:{scope}:{key}`` is a ZSET whose members are unique per-attempt
    tokens scored by their timestamp. A check first evicts entries older than
    the window, then only adds a new member (and extends the key's TTL) if the
    remaining count is still under the limit — a rejected attempt is not
    recorded, so the client becomes eligible again as soon as the oldest
    recorded attempt slides out of the window, exactly as the in-memory
    implementation behaves.
    """

    def __init__(self) -> None:
        self._counter = 0
        self._counter_lock = threading.Lock()

    def _member(self, now: float) -> str:
        with self._counter_lock:
            self._counter += 1
            n = self._counter
        return f"{now}:{n}"

    async def acheck(self, scope: str, key: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        redis_key = f"rl:{scope}:{key}"
        now = time.time()
        client = get_async_redis()

        await client.zremrangebyscore(redis_key, 0, now - window_seconds)
        count = await client.zcard(redis_key)

        if count >= limit:
            oldest = await client.zrange(redis_key, 0, 0, withscores=True)
            oldest_ts = oldest[0][1] if oldest else now
            retry_after = int(window_seconds - (now - oldest_ts)) + 1
            return False, max(retry_after, 1)

        await client.zadd(redis_key, {self._member(now): now})
        await client.expire(redis_key, int(window_seconds) + 1)
        return True, 0


_limiter = RateLimiter()
_redis_limiter = RedisRateLimiter()
_logger = get_logger("rate_limit")


def get_rate_limiter() -> RateLimiter | RedisRateLimiter:
    """Return the process-wide rate limiter for the configured backend.

    ``RATE_LIMIT_BACKEND=redis`` (set by docker-compose for api/ai) returns
    the shared Redis-backed limiter; anything else (default: ``memory``,
    used in tests and local dev without Docker) returns the in-memory one.
    """
    if get_settings().RATE_LIMIT_BACKEND.lower() == "redis":
        return _redis_limiter
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
) -> Callable[[Request], Awaitable[None]]:
    """FastAPI dependency factory enforcing a per-client limit.

    Usage: ``Depends(rate_limit("auth:login", 10, 60))``
    """

    async def _dependency(request: Request) -> None:
        key = key_func(request) if key_func is not None else _client_key(request)
        allowed, retry_after = await get_rate_limiter().acheck(scope, key, limit, window_seconds)
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


def auth_login_limit() -> Callable[[Request], Awaitable[None]]:
    """Tight per-IP limit for credential attempts."""
    settings = get_settings()
    return rate_limit("auth:login", settings.RATE_LIMIT_LOGIN_LIMIT, settings.RATE_LIMIT_DEFAULT_WINDOW_SECONDS)


def auth_register_limit() -> Callable[[Request], Awaitable[None]]:
    """Tight per-IP limit for new-account creation (spam protection)."""
    settings = get_settings()
    return rate_limit("auth:register", settings.RATE_LIMIT_REGISTER_LIMIT, settings.RATE_LIMIT_DEFAULT_WINDOW_SECONDS)


def auth_refresh_limit() -> Callable[[Request], Awaitable[None]]:
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
        allowed, retry_after = await get_rate_limiter().acheck(
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
