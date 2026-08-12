"""Add org_invites and workspace_members tables, audit_logs.organization_id

Phase 13 team collaboration: org_invites lets an admin invite an email
address to join the org at a given role (only the SHA-256 hash of the raw
invite token is stored). workspace_members is an additive, optional
per-workspace role override on top of org-level membership.
audit_logs.organization_id (nullable) lets the new team activity feed scope
entries to one org without cross-tenant leakage; older rows and a few
internal-only actions (auth, MCP tool calls, AI guardrails) are left NULL
and simply don't appear in the feed.

Revision ID: d3e4f5a6b7c9d0e1
Revises: c2d3e4f5a6b7c9d0
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c9d0e1'
down_revision: Union[str, None] = 'c2d3e4f5a6b7c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS org_invites (
            id UUID NOT NULL PRIMARY KEY,
            organization_id UUID NOT NULL,
            email VARCHAR(255) NOT NULL,
            role VARCHAR(50) NOT NULL DEFAULT 'member',
            token_hash VARCHAR(64) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            invited_by UUID NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            accepted_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_org_invites_organization_id
                FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE,
            CONSTRAINT fk_org_invites_invited_by
                FOREIGN KEY (invited_by) REFERENCES users (id)
        )
    """)
    op.create_index('ix_org_invites_org_status', 'org_invites', ['organization_id', 'status'])
    op.create_index('ix_org_invites_token_hash', 'org_invites', ['token_hash'])

    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_members (
            id UUID NOT NULL PRIMARY KEY,
            workspace_id UUID NOT NULL,
            user_id UUID NOT NULL,
            role VARCHAR(50) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_workspace_members_workspace_id
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT fk_workspace_members_user_id
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            CONSTRAINT uq_workspace_user UNIQUE (workspace_id, user_id)
        )
    """)
    op.create_index('ix_workspace_members_workspace', 'workspace_members', ['workspace_id'])

    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS organization_id UUID")
    op.create_index('ix_audit_logs_org_created', 'audit_logs', ['organization_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_audit_logs_org_created', table_name='audit_logs')
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS organization_id")

    op.drop_index('ix_workspace_members_workspace', table_name='workspace_members')
    op.execute("DROP TABLE IF EXISTS workspace_members")

    op.drop_index('ix_org_invites_org_status', table_name='org_invites')
    op.drop_index('ix_org_invites_token_hash', table_name='org_invites')
    op.execute("DROP TABLE IF EXISTS org_invites")
