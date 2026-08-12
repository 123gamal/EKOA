"""Add retrieval_latency_ms to ai_call_logs

Phase 12: separates embedding + Qdrant search time from LLM-only latency
(the existing latency_ms column) so the two dominant cost centers of a chat
turn are distinguishable in AiCallLog without re-deriving them from raw
structured logs. Populated by apps/ai/graph.py's retriever_node.

Revision ID: c2d3e4f5a6b7c9d0
Revises: b1c2d3e4f5a6b7c9
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7c9d0'
down_revision: Union[str, None] = 'b1c2d3e4f5a6b7c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ai_call_logs
            ADD COLUMN IF NOT EXISTS retrieval_latency_ms BIGINT
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE ai_call_logs DROP COLUMN IF EXISTS retrieval_latency_ms")
