"""Conversation and message Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ConversationResponse(BaseModel):
    """Serialised conversation returned by list/get endpoints."""

    id: UUID
    title: str | None = None
    workspace_id: UUID
    organization_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    """Serialised message returned by conversation history endpoints."""

    id: UUID
    conversation_id: UUID
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
