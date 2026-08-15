"""Add OAuth2 fields to connector_credentials

Phase 14 connectors: Slack/Google Drive use OAuth2 instead of a pasted PAT.
Google's access tokens expire (~1hr) and need a refresh token to renew
silently; Slack's bot tokens don't expire but the columns are shared/nullable
so every provider uses the same table.

Revision ID: e4f5a6b7c9d0e1f2
Revises: d3e4f5a6b7c9d0e1
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c9d0e1f2'
down_revision: Union[str, None] = 'd3e4f5a6b7c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE connector_credentials ADD COLUMN IF NOT EXISTS refresh_token_encrypted TEXT"
    )
    op.execute(
        "ALTER TABLE connector_credentials ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMP WITH TIME ZONE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE connector_credentials DROP COLUMN IF EXISTS token_expires_at")
    op.execute("ALTER TABLE connector_credentials DROP COLUMN IF EXISTS refresh_token_encrypted")
