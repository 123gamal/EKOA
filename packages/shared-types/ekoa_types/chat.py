"""Chat and agent-interaction Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """A single message in a conversation."""

    role: str = Field(..., description="'user', 'assistant', or 'system'.")
    content: str = Field(..., min_length=1)


class AgentAction(BaseModel):
    """An intermediate action taken by the agent (tool call, retrieval, etc.)."""

    tool_name: str
    tool_input: dict[str, object] = Field(default_factory=dict)
    tool_output: str | None = None
    timestamp: datetime | None = None


class ChatRequest(BaseModel):
    """Payload sent by the client to start / continue a conversation."""

    workspace_id: UUID
    conversation_id: UUID | None = None
    message: str = Field(..., min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Response returned to the client after agent processing."""

    conversation_id: UUID
    reply: str
    sources: list[str] = Field(default_factory=list)
    actions: list[AgentAction] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
