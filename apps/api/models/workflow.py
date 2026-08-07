from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List
from sqlalchemy import String, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from apps.api.models.workspace import Workspace
    from apps.api.models.user import User


class Workflow(Base, TimestampMixin):
    """Workflow model representing a user-created automation definition."""
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)  # DRAFT, RUNNING, COMPLETED, FAILED
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace: Mapped[Workspace] = relationship(back_populates="workflows")
    creator: Mapped[User] = relationship(foreign_keys=[created_by], back_populates="workflows")
    runs: Mapped[List[WorkflowRun]] = relationship(back_populates="workflow", cascade="all, delete-orphan")


class WorkflowRun(Base, TimestampMixin):
    """WorkflowRun model capturing one execution attempt of a workflow."""
    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)  # PENDING, RUNNING, AWAITING_APPROVAL, COMPLETED, FAILED, REJECTED
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    steps: Mapped[list | None] = mapped_column(JSON, nullable=True)   # list of {name, type, status, output, duration_ms, data}
    logs: Mapped[list | None] = mapped_column(JSON, nullable=True)     # list of {ts, level, message}
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Human-in-the-loop approval state. ``approved_by`` / ``approved_at`` carry
    # the identity and time of whoever made the decision, whether that decision
    # was an approval or a rejection (the outcome lives in ``approval_status``).
    approval_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # PENDING, APPROVED, REJECTED
    approval_step_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    workflow: Mapped[Workflow] = relationship(back_populates="runs")
    approver: Mapped[User | None] = relationship(foreign_keys=[approved_by])
