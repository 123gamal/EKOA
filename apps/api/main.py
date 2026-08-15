from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from apps.api.routes import (
    auth,
    organizations,
    workspaces,
    documents,
    workflows,
    analytics,
    connectors,
    mcp_keys,
    invites,
    activity,
    oauth,
)
from apps.api.db.engine import get_engine
from ekoa_config.settings import get_settings, resolve_cors_origins
from ekoa_config.logging import setup_logging, CorrelationIdMiddleware
from ekoa_config.rate_limit import RateLimitMiddleware
from ekoa_config.redis_client import get_async_redis

# Import models so they are registered on Base.metadata (required for Alembic
# autogenerate; the schema itself is applied by migrations, not create_all).
import apps.api.models.user  # noqa: F401  (side-effect: registers model on Base.metadata)
import apps.api.models.organization  # noqa: F401
import apps.api.models.org_member  # noqa: F401
import apps.api.models.workspace  # noqa: F401
import apps.api.models.document  # noqa: F401
import apps.api.models.session  # noqa: F401
import apps.api.models.audit_log  # noqa: F401
import apps.api.models.workflow  # noqa: F401
import apps.api.models.connector  # noqa: F401
import apps.api.models.mcp_api_key  # noqa: F401
import apps.api.models.org_invite  # noqa: F401
import apps.api.models.workspace_member  # noqa: F401

setup_logging("api")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan hook.

    Schema is managed exclusively through Alembic migrations
    (apps.api.alembic). No runtime ``create_all`` here: that path silently
    drifted from the migration set and masked missing tables.
    """
    yield


app = FastAPI(
    title="EKOA Core API",
    description="Enterprise Knowledge Operations Assistant REST backend",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware from settings. The origins list is validated at startup:
# combining allow_credentials=True with "*" raises a RuntimeError instead of
# silently misconfiguring cross-origin requests.
cors_origins = resolve_cors_origins(settings)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Correlation middleware added after CORS so it runs closest to the handlers
# and its request log line covers the handled request/response.
app.add_middleware(CorrelationIdMiddleware)

# General default per-IP rate limit for every request (except /health). Tight
# per-route limits for /auth/login, /auth/register, /auth/refresh are declared
# as dependencies on those routes in apps.api.routes.auth.
app.add_middleware(RateLimitMiddleware)

# Register routers
app.include_router(auth.router)
app.include_router(organizations.router)
app.include_router(workspaces.router)
app.include_router(documents.router)
app.include_router(workflows.router)
app.include_router(analytics.router)
app.include_router(connectors.router)
app.include_router(mcp_keys.router)
app.include_router(invites.router)
app.include_router(activity.router)
app.include_router(oauth.router)


@app.get("/")
async def root():
    return {
        "message": "Welcome to EKOA Core API",
        "version": "0.1.0",
        "docs_url": "/docs"
    }


@app.get("/health")
async def health_check():
    """Liveness probe that verifies real dependencies, not just the process.

    Returns 200 only when the database is reachable; otherwise 503 so Docker
    healthchecks fail for an actually-degraded service.
    """
    dependencies: dict[str, str] = {}
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        dependencies["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        dependencies["database"] = f"error: {type(exc).__name__}"

    try:
        await get_async_redis().ping()
        dependencies["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        dependencies["redis"] = f"error: {type(exc).__name__}"

    healthy = all(v == "ok" for v in dependencies.values())
    body = {
        "status": "healthy" if healthy else "unhealthy",
        "service": "ekoa-api",
        "version": "0.1.0",
        "dependencies": dependencies,
    }
    if not healthy:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=body)
    return body
