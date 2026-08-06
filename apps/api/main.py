from __future__ import annotations

import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes import auth, organizations, workspaces, documents, workflows, analytics
from ekoa_config.settings import get_settings

# Import models so they are registered on Base.metadata (required for Alembic
# autogenerate; the schema itself is applied by migrations, not create_all).
import apps.api.models.user
import apps.api.models.organization
import apps.api.models.org_member
import apps.api.models.workspace
import apps.api.models.document
import apps.api.models.session
import apps.api.models.audit_log
import apps.api.models.workflow

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

# CORS middleware from settings
try:
    cors_origins = json.loads(settings.CORS_ORIGINS)
except (json.JSONDecodeError, TypeError):
    cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(organizations.router)
app.include_router(workspaces.router)
app.include_router(documents.router)
app.include_router(workflows.router)
app.include_router(analytics.router)


@app.get("/")
async def root():
    return {
        "message": "Welcome to EKOA Core API",
        "version": "0.1.0",
        "docs_url": "/docs"
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "ekoa-api",
        "version": "0.1.0"
    }
