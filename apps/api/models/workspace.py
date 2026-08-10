from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List
from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from apps.api.models.organization import Organization
    from apps.api.models.user import User
    from apps.api.models.document import Document
    from apps.api.models.workflow import Workflow
    from apps.api.models.conversation import Conversation
    from apps.api.models.connector import Connector


class Workspace(Base, TimestampMixin):
    """Workspace model representing groups of documents and conversations inside an Organization."""
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="workspaces")
    creator: Mapped[User] = relationship(foreign_keys=[created_by], back_populates="created_workspaces")
    documents: Mapped[List[Document]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    workflows: Mapped[List[Workflow]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    conversations: Mapped[List[Conversation]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    connectors: Mapped[List[Connector]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
