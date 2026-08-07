from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from apps.api.models.document import Document
    from apps.api.models.user import User


class DocumentVersion(Base, TimestampMixin):
    """DocumentVersion model tracking revisions of an ingested file.

    Version 1 is created on upload. Re-upload (version N+1) is intentionally not
    implemented yet — TODO(phase5): add a re-upload flow that increments
    ``version``, re-indexes, and snapshots the previous version.
    """
    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)  # sha256 hex digest
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)  # mirrors Document.status
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Relationships
    document: Mapped[Document] = relationship(back_populates="versions")
    uploader: Mapped[User] = relationship(foreign_keys=[uploaded_by], back_populates="document_versions")
