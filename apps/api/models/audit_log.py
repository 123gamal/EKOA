from __future__ import annotations

import uuid
from sqlalchemy import String, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from apps.api.db.base import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    """AuditLog model for recording sensitive system and user operations."""
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Nullable + added in Phase 13: only rows written since then (from routes
    # that pass it) are org-scoped; used by the team activity feed to avoid
    # cross-tenant leakage. Older/internal-only rows are simply excluded.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "auth.login", "document.upload"
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
