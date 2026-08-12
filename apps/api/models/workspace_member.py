from __future__ import annotations

import uuid
from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from apps.api.db.base import Base, TimestampMixin


class WorkspaceMember(Base, TimestampMixin):
    """Optional per-workspace role override for a user (Phase 13).

    Additive on top of org-level membership: most authorization still keys
    off :class:`~apps.api.models.org_member.OrgMember`.role via
    ``apps.api.dependencies.authz``. A row here only exists when an org admin
    has explicitly set a member's role *within a specific workspace*
    (e.g. workspace-admin without org-admin); absence of a row means "use the
    org role" (see ``authz.get_workspace_role``).
    """
    __tablename__ = "workspace_members"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # 'owner', 'admin', 'member'

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),
    )
