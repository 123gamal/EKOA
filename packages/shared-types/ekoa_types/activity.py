"""Team activity feed schema (Phase 13) — a read-only view over AuditLog."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ActivityEntry(BaseModel):
    id: UUID
    user_id: UUID | None
    actor_name: str | None = None
    actor_email: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: UUID | None = None
    details: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
