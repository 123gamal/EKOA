"""Add mcp_api_keys table

Phase 8 MCP API key management: org/workspace-scoped bearer keys for the
EKOA MCP server. Only the SHA-256 hash of the raw key (plus a short
identifying prefix) is stored — the plaintext is returned once at creation
and is not reversible.

Revision ID: 1c2d3e4f5a6b7c8d
Revises: f0a1b2c3d4e5f607
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '1c2d3e4f5a6b7c8d'
down_revision: Union[str, None] = 'f0a1b2c3d4e5f607'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS mcp_api_keys (
            id UUID NOT NULL PRIMARY KEY,
            organization_id UUID NOT NULL,
            workspace_id UUID NOT NULL,
            name VARCHAR(255) NOT NULL,
            key_hash VARCHAR(64) NOT NULL,
            key_prefix VARCHAR(32) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_by UUID NOT NULL,
            last_used_at TIMESTAMP WITH TIME ZONE,
            revoked_at TIMESTAMP WITH TIME ZONE,
            revoked_by UUID,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_mcp_api_keys_organization_id
                FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE,
            CONSTRAINT fk_mcp_api_keys_workspace_id
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT fk_mcp_api_keys_created_by
                FOREIGN KEY (created_by) REFERENCES users (id),
            CONSTRAINT fk_mcp_api_keys_revoked_by
                FOREIGN KEY (revoked_by) REFERENCES users (id)
        )
    """)
    op.create_index('ix_mcp_api_keys_workspace_created', 'mcp_api_keys', ['workspace_id', 'created_at'])
    op.create_index('ix_mcp_api_keys_key_hash', 'mcp_api_keys', ['key_hash'])


def downgrade() -> None:
    op.drop_index('ix_mcp_api_keys_workspace_created', table_name='mcp_api_keys')
    op.drop_index('ix_mcp_api_keys_key_hash', table_name='mcp_api_keys')
    op.execute("DROP TABLE IF EXISTS mcp_api_keys")