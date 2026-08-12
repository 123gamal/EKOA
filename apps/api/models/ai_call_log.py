from __future__ import annotations

import uuid

from sqlalchemy import String, Text, ForeignKey, BigInteger, Boolean, Numeric, Index
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, TimestampMixin


class AiCallLog(Base, TimestampMixin):
    """Per-call LLM telemetry for the AI chat path (FR-1000 observability).

    One row per real chat completion. Turns the Phase 2 structured-log lines
    (provider, latency, token counts) and the Phase 5 flags (guardrails,
    citation integrity) into queryable data. All token/latency fields are
    nullable because a provider may not report them and degraded/fallback
    calls have no real provider response at all.

    ``cost_estimate`` is a rough USD estimate derived from token counts and
    list prices — explicitly NOT a billed amount (see ekoa_utils.cost).
    """

    __tablename__ = "ai_call_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Embedding + Qdrant search time only, separate from latency_ms (LLM-only)
    # — added Phase 12 to make the two dominant cost centers of a chat turn
    # distinguishable without re-deriving them from raw logs.
    retrieval_latency_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    guardrail_triggered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    citations_dropped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    cost_estimate: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_ai_call_logs_workspace_created", "workspace_id", "created_at"),
    )