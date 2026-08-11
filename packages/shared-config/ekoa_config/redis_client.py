"""Shared Redis client factories for the API, AI, and worker services.

Two singletons, mirroring the sync/async split already present elsewhere in
the codebase (e.g. ``apps.ai.retriever`` is sync, ``apps.api`` is async):

- :func:`get_async_redis` — for FastAPI request handlers, middleware, and the
  rate limiter (``redis.asyncio``).
- :func:`get_sync_redis` — for non-async call sites such as the AI retriever's
  ``retrieve_chunks`` (plain ``redis``).

Both are process-wide singletons built from ``REDIS_URL``; callers should
treat Redis as a pure optimization layer (rate limiting aside, which is a
correctness feature) — any connection error should be caught by the caller
and treated as a cache miss / fall through to the uncached path, never as a
fatal error.
"""

from __future__ import annotations

from functools import lru_cache

import redis
import redis.asyncio as aredis

from ekoa_config.settings import get_settings


@lru_cache(maxsize=1)
def get_async_redis() -> aredis.Redis:
    """Return the process-wide async Redis client singleton."""
    settings = get_settings()
    return aredis.from_url(settings.REDIS_URL, decode_responses=True)


@lru_cache(maxsize=1)
def get_sync_redis() -> redis.Redis:
    """Return the process-wide sync Redis client singleton."""
    settings = get_settings()
    return redis.from_url(settings.REDIS_URL, decode_responses=True)
