"""Add human-in-the-loop approval fields to workflow_runs

Phase 5 HITL gate. The compliance-audit workflow now pauses for a human
decision instead of auto-continuing when sensitive data is found. These
columns record the approval lifecycle on the run row:

- approval_status:  PENDING -> APPROVED | REJECTED (NULL when no approval gate)
- approval_step_id: the template step id that triggered the pause (e.g. "s3")
- approved_by:      who made the decision (approval or rejection)
- approved_at:      when the decision was made
- approval_reason:  optional comment from the decision maker

``approved_by`` / ``approved_at`` carry the reviewer identity and timestamp
regardless of outcome; ``approval_status`` distinguishes the outcome.

Revision ID: a85f6b7c8d9ea0b1
Revises: f74f5a6b7c8d9ea3
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a85f6b7c8d9ea0b1'
down_revision: Union[str, None] = 'f74f5a6b7c8d9ea3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('workflow_runs', sa.Column('approval_status', sa.String(length=20), nullable=True))
    op.add_column('workflow_runs', sa.Column('approval_step_id', sa.String(length=50), nullable=True))
    op.add_column('workflow_runs', sa.Column('approved_by', sa.UUID(), nullable=True))
    op.add_column('workflow_runs', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('workflow_runs', sa.Column('approval_reason', sa.Text(), nullable=True))
    op.create_foreign_key(
        'fk_workflow_runs_approved_by', 'workflow_runs', 'users', ['approved_by'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_workflow_runs_status_approval_status', 'workflow_runs', ['status', 'approval_status'])


def downgrade() -> None:
    op.drop_index('ix_workflow_runs_status_approval_status', table_name='workflow_runs')
    op.drop_constraint('fk_workflow_runs_approved_by', 'workflow_runs', type_='foreignkey')
    op.drop_column('workflow_runs', 'approval_reason')
    op.drop_column('workflow_runs', 'approved_at')
    op.drop_column('workflow_runs', 'approved_by')
    op.drop_column('workflow_runs', 'approval_step_id')
    op.drop_column('workflow_runs', 'approval_status')
