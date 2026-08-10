"""Add connectors and connector_credentials tables

Phase 7 connector framework: generalized Connector model (org/workspace scoped,
provider name, status connected/error/disconnected, connected-by, timestamps,
last-sync time/status) plus a one-to-one ConnectorCredential row holding the
access token as Fernet-encrypted ciphertext at rest.

Revision ID: f0a1b2c3d4e5f607
Revises: b4f5c6d7e8f9a0b1
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5f607'
down_revision: Union[str, None] = 'b4f5c6d7e8f9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS connectors (
            id UUID NOT NULL PRIMARY KEY,
            organization_id UUID NOT NULL,
            workspace_id UUID NOT NULL,
            provider VARCHAR(50) NOT NULL,
            name VARCHAR(255) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'disconnected',
            status_reason TEXT,
            connected_by UUID NOT NULL,
            connected_at TIMESTAMP WITH TIME ZONE,
            last_sync_at TIMESTAMP WITH TIME ZONE,
            last_sync_status VARCHAR(20),
            last_sync_error TEXT,
            last_sync_document_count INTEGER,
            config_json JSONB,
            deleted_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_connectors_organization_id
                FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE,
            CONSTRAINT fk_connectors_workspace_id
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT fk_connectors_connected_by
                FOREIGN KEY (connected_by) REFERENCES users (id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS connector_credentials (
            id UUID NOT NULL PRIMARY KEY,
            connector_id UUID NOT NULL UNIQUE,
            token_type VARCHAR(50) NOT NULL DEFAULT 'pat',
            access_token_encrypted TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_connector_credentials_connector_id
                FOREIGN KEY (connector_id) REFERENCES connectors (id) ON DELETE CASCADE
        )
    """)
    op.create_index('ix_connectors_workspace_provider', 'connectors', ['workspace_id', 'provider'])
    op.create_index('ix_connectors_org_created', 'connectors', ['organization_id', 'created_at'])
    op.create_index('ix_connector_credentials_connector_id', 'connector_credentials', ['connector_id'])


def downgrade() -> None:
    op.drop_index('ix_connector_credentials_connector_id', table_name='connector_credentials')
    op.drop_index('ix_connectors_org_created', table_name='connectors')
    op.drop_index('ix_connectors_workspace_provider', table_name='connectors')
    op.execute("DROP TABLE IF EXISTS connector_credentials")
    op.execute("DROP TABLE IF EXISTS connectors")
