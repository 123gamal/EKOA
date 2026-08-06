"""Workspace-related Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceBase(BaseModel):
    """Fields shared across workspace representations."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class WorkspaceCreate(WorkspaceBase):
    """Payload for creating a new workspace."""

    organization_id: UUID


class WorkspaceResponse(WorkspaceBase):
    """Serialised workspace returned by API endpoints."""

    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
