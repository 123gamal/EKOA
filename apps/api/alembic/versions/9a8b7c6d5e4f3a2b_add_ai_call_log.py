"""Add ai_call_logs table

Phase 9 AI evaluation & observability: one row per real chat completion,
turning the Phase 2 structured-log line (provider, latency, tokens) and the
Phase 5 flags (guardrails, citation integrity) into queryable data for the
model-performance / knowledge-insights aggregation.

Revision ID: 9a8b7c6d5e4f3a2b
Revises: 1c2d3e4f5a6b7c8d
Create Date: 2026-08-11 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '9a8b7c6d5e4f3a2b'
down_revision: Union[str, None] = '1c2d3e4f5a6b7c8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_call_logs (
            id UUID NOT NULL PRIMARY KEY,
            organization_id UUID NOT NULL,
            workspace_id UUID NOT NULL,
            conversation_id UUID,
            message_id UUID,
            user_id UUID,
            provider VARCHAR(50),
            model VARCHAR(100),
            latency_ms BIGINT,
            prompt_tokens BIGINT,
            completion_tokens BIGINT,
            total_tokens BIGINT,
            degraded BOOLEAN NOT NULL DEFAULT FALSE,
            guardrail_triggered BOOLEAN NOT NULL DEFAULT FALSE,
            citations_dropped BOOLEAN NOT NULL DEFAULT FALSE,
            cost_estimate NUMERIC(12, 6),
            error TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_ai_call_logs_organization_id
                FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE,
            CONSTRAINT fk_ai_call_logs_workspace_id
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT fk_ai_call_logs_conversation_id
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE SET NULL,
            CONSTRAINT fk_ai_call_logs_message_id
                FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE SET NULL,
            CONSTRAINT fk_ai_call_logs_user_id
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
        )
    """)
    op.create_index(
        'ix_ai_call_logs_workspace_created', 'ai_call_logs', ['workspace_id', 'created_at']
    )


def downgrade() -> None:
    op.drop_index('ix_ai_call_logs_workspace_created', table_name='ai_call_logs')
    op.execute("DROP TABLE IF EXISTS ai_call_logs")