from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from apps.api.models.organization import Organization
    from apps.api.models.workspace import Workspace
    from apps.api.models.user import User


class McpApiKey(Base, TimestampMixin):
    """A bearer API key for the MCP server, scoped to one workspace.

    Only ``key_hash`` (SHA-256 hex digest of the raw key) and ``key_prefix``
    are stored — the raw key is shown once at creation and is not reversible.
    ``status`` is ``active`` or ``revoked``; the MCP server rejects a revoked
    key outright.
    """
    __tablename__ = "mcp_api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 hex
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)  # identifying prefix only
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )  # active | revoked
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # null = never expires
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="mcp_api_keys")
    workspace: Mapped[Workspace] = relationship(back_populates="mcp_api_keys")
    creator: Mapped[User] = relationship(
        foreign_keys=[created_by], back_populates="created_mcp_api_keys"
    )