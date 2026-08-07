"""Add deleted_at columns for soft deletes

Phase 4 soft deletes: adds a nullable deleted_at timestamp to the core tables
that support deletion (documents, workspaces, organizations, workflows).
Deletion endpoints set this column instead of removing rows; list/get
queries filter on it. No hard-delete/purge feature is introduced.

Revision ID: e63f4a5b6c7d8e92
Revises: d52f3a4b5c6d7e81
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e63f4a5b6c7d8e92'
down_revision: Union[str, None] = 'd52f3a4b5c6d7e81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('workspaces', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('organizations', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('workflows', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('workflows', 'deleted_at')
    op.drop_column('organizations', 'deleted_at')
    op.drop_column('workspaces', 'deleted_at')
    op.drop_column('documents', 'deleted_at')
