"""Document-related Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentStatus(str, Enum):
    """Processing lifecycle states for a document."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    ENQUEUE_FAILED = "ENQUEUE_FAILED"


class DocumentBase(BaseModel):
    """Fields shared across document representations."""

    title: str = Field(..., min_length=1, max_length=512)
    content_type: str = Field(
        default="text/plain",
        max_length=127,
        description="MIME type of the original file.",
    )


class DocumentCreate(DocumentBase):
    """Payload for creating / uploading a new document."""

    workspace_id: UUID
    source_url: str | None = None


class DocumentResponse(DocumentBase):
    """Serialised document returned by API endpoints."""

    id: UUID
    workspace_id: UUID
    source_url: str | None = None
    status: DocumentStatus = DocumentStatus.PENDING
    chunk_count: int = 0
    metadata_json: dict | None = Field(default=None, alias="metadata_json")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
