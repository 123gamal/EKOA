"""Connector-related Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConnectorStatus(str, Enum):
    """Lifecycle states for a connector."""

    CONNECTED = "connected"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ConnectorLastSyncStatus(str, Enum):
    """Outcome of the most recent sync run."""

    SUCCESS = "success"
    FAILED = "failed"
    RUNNING = "running"


class GitHubConfig(BaseModel):
    """Provider-specific config for the GitHub connector."""

    owner: str = Field(..., min_length=1, max_length=255)
    repo: str = Field(..., min_length=1, max_length=255)


class ConnectorConnectRequest(BaseModel):
    """Payload for connecting a new integration."""

    provider: str = Field(..., min_length=1, max_length=50)
    workspace_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    access_token: str = Field(..., min_length=1, max_length=512)
    config: GitHubConfig | dict = Field(..., description="Provider-specific configuration (e.g. owner/repo for GitHub)")


class ConnectorResponse(BaseModel):
    """Serialised connector returned by API endpoints.

    Deliberately does NOT expose the access token (or any credential fields).
    """

    id: UUID
    organization_id: UUID
    workspace_id: UUID
    provider: str
    name: str
    status: ConnectorStatus
    status_reason: str | None = None
    connected_by: UUID
    connected_at: datetime | None = None
    last_sync_at: datetime | None = None
    last_sync_status: ConnectorLastSyncStatus | None = None
    last_sync_error: str | None = None
    last_sync_document_count: int | None = None
    config: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ConnectorHealthResponse(BaseModel):
    """Real health state of a connector: credential validity + last sync."""

    id: UUID
    provider: str
    name: str
    status: ConnectorStatus
    token_valid: bool
    detail: str
    last_sync_at: datetime | None = None
    last_sync_status: ConnectorLastSyncStatus | None = None
    last_sync_error: str | None = None


class ConnectorSyncResponse(BaseModel):
    """Response after triggering a manual sync."""

    id: UUID
    status: str = Field(..., description="e.g. 'sync_triggered' or 'sync_running'")
    detail: str
