"""In-app notification schema (Phase 16 Part B-3)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    id: UUID
    type: str
    title: str
    body: str | None = None
    resource_type: str | None = None
    resource_id: UUID | None = None
    read_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
