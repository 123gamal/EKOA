"""Workspace-level role override schemas (Phase 13, additive on top of org roles)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WorkspaceMemberOverrideRequest(BaseModel):
    """Set a member's role override within a specific workspace."""

    role: Literal["owner", "admin", "member"]


class WorkspaceMemberOverrideResponse(BaseModel):
    workspace_id: UUID
    user_id: UUID
    role: str

    model_config = ConfigDict(from_attributes=True)
