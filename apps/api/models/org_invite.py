from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from apps.api.db.base import Base, TimestampMixin


class OrgInvite(Base, TimestampMixin):
    """An invitation for an email address to join an organization at a given role.

    Only ``token_hash`` (SHA-256 hex digest) is stored — the raw token is
    embedded once in the invite email and is not reversible, mirroring
    :class:`~apps.api.models.mcp_api_key.McpApiKey`. ``status`` is
    ``pending``, ``accepted``, or ``revoked``.
    """
    __tablename__ = "org_invites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 hex
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | accepted | revoked
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
