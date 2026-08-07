from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from apps.api.models.user import User
    from apps.api.models.organization import Organization


class OrgMember(Base, TimestampMixin):
    """Association model representing members of organizations and their roles."""
    __tablename__ = "org_members"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)  # 'owner', 'admin', 'member'

    # Relationships
    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship(back_populates="members")

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_user_organization"),
    )
