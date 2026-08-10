from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List
from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from apps.api.models.user import User
    from apps.api.models.org_member import OrgMember
    from apps.api.models.workspace import Workspace
    from apps.api.models.conversation import Conversation
    from apps.api.models.connector import Connector


class Organization(Base, TimestampMixin):
    """Organization/Tenant model representing first-class entities in EKOA."""
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner: Mapped[User] = relationship(foreign_keys=[owner_id])
    members: Mapped[List[OrgMember]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    workspaces: Mapped[List[Workspace]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    conversations: Mapped[List[Conversation]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    connectors: Mapped[List[Connector]] = relationship(back_populates="organization", cascade="all, delete-orphan")
