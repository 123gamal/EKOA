from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from apps.api.models.organization import Organization
    from apps.api.models.workspace import Workspace
    from apps.api.models.user import User


class Connector(Base, TimestampMixin):
    """A connected external integration (e.g. a GitHub repository).

    Holds provider-agnostic connection state. Credentials are stored in the
    one-to-one ``ConnectorCredential`` as Fernet-encrypted ciphertext, never
    in plaintext.
    """
    __tablename__ = "connectors"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "github"
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # display name / repo
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="disconnected"
    )  # connected | error | disconnected
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # success | failed | running
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_document_count: Mapped[int | None] = mapped_column(nullable=True)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # provider-specific config
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    organization: Mapped[Organization] = relationship(back_populates="connectors")
    workspace: Mapped[Workspace] = relationship(back_populates="connectors")
    connector_user: Mapped[User] = relationship(
        foreign_keys=[connected_by], back_populates="connected_connectors"
    )
    credential: Mapped[Optional[ConnectorCredential]] = relationship(
        back_populates="connector",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ConnectorCredential(Base, TimestampMixin):
    """Encrypted credential material for a :class:`Connector`.

    ``access_token_encrypted`` holds Fernet ciphertext of the access token;
    the plaintext never touches the database.
    """
    __tablename__ = "connector_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    connector_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    token_type: Mapped[str] = mapped_column(String(50), default="pat", nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    connector: Mapped[Connector] = relationship(back_populates="credential")
