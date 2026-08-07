"""Align workflow_runs started_at / completed_at with timezone-aware UTC

The rest of the schema (TimestampMixin) stores timestamps with timezone.
started_at / completed_at were inferred as naive TIMESTAMP WITHOUT TIME ZONE,
which the asyncpg dialect rejects when the application writes
``datetime.now(timezone.utc)`` (offset-aware). Promote both columns to
``timestamp with time zone`` so approval/run timestamps round-trip cleanly.

Revision ID: b4f5c6d7e8f9a0b1
Revises: a85f6b7c8d9ea0b1
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b4f5c6d7e8f9a0b1'
down_revision: Union[str, None] = 'a85f6b7c8d9ea0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Only run on Postgres; SQLite is used for tests and handles both fine.
    if op.get_context().dialect.name == "postgresql":
        op.alter_column(
            'workflow_runs', 'started_at',
            existing_type=postgresql.TIMESTAMP(),
            type_=postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        )
        op.alter_column(
            'workflow_runs', 'completed_at',
            existing_type=postgresql.TIMESTAMP(),
            type_=postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.alter_column(
            'workflow_runs', 'started_at',
            existing_type=postgresql.TIMESTAMP(timezone=True),
            type_=postgresql.TIMESTAMP(),
            nullable=True,
        )
        op.alter_column(
            'workflow_runs', 'completed_at',
            existing_type=postgresql.TIMESTAMP(timezone=True),
            type_=postgresql.TIMESTAMP(),
            nullable=True,
        )
