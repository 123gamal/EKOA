"""Add document_versions table

Phase 4 document versioning: version 1 is created on upload alongside the
document row. Re-upload (version N+1) is a future phase.

Revision ID: d52f3a4b5c6d7e81
Revises: c41f2a3b4d5e6f70
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd52f3a4b5c6d7e81'
down_revision: Union[str, None] = 'c41f2a3b4d5e6f70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_versions (
            id UUID NOT NULL PRIMARY KEY,
            document_id UUID NOT NULL,
            version INTEGER NOT NULL,
            file_path TEXT,
            checksum VARCHAR(64),
            status VARCHAR(20) NOT NULL,
            uploaded_by UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_document_versions_document_id
                FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
            CONSTRAINT fk_document_versions_uploaded_by
                FOREIGN KEY (uploaded_by) REFERENCES users (id)
        )
    """)
    op.create_index(
        'ix_document_versions_document_id_version',
        'document_versions',
        ['document_id', 'version'],
    )


def downgrade() -> None:
    op.drop_index('ix_document_versions_document_id_version', table_name='document_versions')
    op.execute("DROP TABLE IF EXISTS document_versions")
