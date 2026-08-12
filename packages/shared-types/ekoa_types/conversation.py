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
    # Populated by list_conversations (Phase 13) so the UI can show who
    # started a shared conversation without a second request; None when not
    # explicitly filled in (e.g. constructed straight from the ORM object
    # elsewhere in this file).
    owner_name: str | None = None
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
