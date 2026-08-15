"""Org-level admin console schema (Phase 16 Part D)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AdminWorkspaceSummary(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    document_count: int
    connector_count: int
    workflow_count: int
    creator_name: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminOrgOverview(BaseModel):
    organization_id: UUID
    organization_name: str
    member_count: int
    workspaces: list[AdminWorkspaceSummary]
