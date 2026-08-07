from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, List
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from apps.api.models.workspace import Workspace
    from apps.api.models.organization import Organization
    from apps.api.models.user import User


class Conversation(Base, TimestampMixin):
    """Conversation model representing a persistent chat session inside a workspace.

    Scoped to an organization (tenant) and workspace for multi-tenant isolation,
    and owned by the user who started it. Messages are stored on the
    :class:`Message` table so history survives across requests and can be
    reloaded from the database on subsequent turns.
    """
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Relationships
    workspace: Mapped[Workspace] = relationship(back_populates="conversations")
    organization: Mapped[Organization] = relationship(back_populates="conversations")
    owner: Mapped[User] = relationship(foreign_keys=[user_id], back_populates="conversations")
    messages: Mapped[List[Message]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base, TimestampMixin):
    """Message model capturing one exchange (user or assistant turn) in a conversation."""
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
