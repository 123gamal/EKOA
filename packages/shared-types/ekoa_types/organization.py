"""Organization-related Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrganizationBase(BaseModel):
    """Fields shared across organization representations."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=127, pattern=r"^[a-z0-9-]+$")
    description: str | None = None


class OrganizationCreate(OrganizationBase):
    """Payload for creating a new organization."""


class OrganizationResponse(OrganizationBase):
    """Serialised organization returned by API endpoints."""

    id: UUID
    owner_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
