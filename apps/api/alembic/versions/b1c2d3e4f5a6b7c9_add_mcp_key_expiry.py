"""Add expires_at to mcp_api_keys

Phase 10: optional TTL for MCP API keys (flagged as missing since Phase 8's
report). NULL means the key never expires — the same behavior as before this
migration for every existing key. Enforced at verification time in
apps.mcp_server.auth (no scheduler/background sweep involved).

Revision ID: b1c2d3e4f5a6b7c9
Revises: 9a8b7c6d5e4f3a2b
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6b7c9'
down_revision: Union[str, None] = '9a8b7c6d5e4f3a2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE mcp_api_keys
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE mcp_api_keys DROP COLUMN IF EXISTS expires_at")
