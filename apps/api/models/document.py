from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List
from sqlalchemy import String, Text, ForeignKey, Integer, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from apps.api.models.workspace import Workspace
    from apps.api.models.user import User
    from apps.api.models.document_version import DocumentVersion


class Document(Base, TimestampMixin):
    """Document model representing ingested files inside a workspace."""
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), default="text/plain", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)  # PENDING, PROCESSING, INDEXED, FAILED, ENQUEUE_FAILED
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace: Mapped[Workspace] = relationship(back_populates="documents")
    uploader: Mapped[User] = relationship(foreign_keys=[uploaded_by], back_populates="uploaded_documents")
    versions: Mapped[List[DocumentVersion]] = relationship(back_populates="document", cascade="all, delete-orphan")
