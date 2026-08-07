"""Add composite indexes for real query patterns

Phase 4 indexing pass. Each index mirrors an actual query shape observed in
the codebase:

- documents: (workspace_id, status)            analytics status grouping
- documents: (workspace_id, created_at)        list_documents ORDER BY created_at DESC
- documents: (workspace_id, deleted_at)        soft-delete filtering
- workflows: (workspace_id, created_at)        list_workflows ORDER BY created_at DESC
- workflow_runs: (workflow_id, status)         run status lookups
- workflow_runs: (workflow_id, created_at)     list_runs ORDER BY created_at DESC
- workspaces: (organization_id, created_at)    list_workspaces ORDER BY created_at DESC
- audit_logs: (user_id, created_at)            analytics recent-activity (audit_logs has
                                               no organization_id column)

Revision ID: f74f5a6b7c8d9ea3
Revises: e63f4a5b6c7d8e92
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f74f5a6b7c8d9ea3'
down_revision: Union[str, None] = 'e63f4a5b6c7d8e92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_documents_workspace_id_status', 'documents', ['workspace_id', 'status'])
    op.create_index('ix_documents_workspace_id_created_at', 'documents', ['workspace_id', 'created_at'])
    op.create_index('ix_documents_workspace_id_deleted_at', 'documents', ['workspace_id', 'deleted_at'])
    op.create_index('ix_workflows_workspace_id_created_at', 'workflows', ['workspace_id', 'created_at'])
    op.create_index('ix_workflow_runs_workflow_id_status', 'workflow_runs', ['workflow_id', 'status'])
    op.create_index('ix_workflow_runs_workflow_id_created_at', 'workflow_runs', ['workflow_id', 'created_at'])
    op.create_index('ix_workspaces_organization_id_created_at', 'workspaces', ['organization_id', 'created_at'])
    op.create_index('ix_audit_logs_user_id_created_at', 'audit_logs', ['user_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_audit_logs_user_id_created_at', table_name='audit_logs')
    op.drop_index('ix_workspaces_organization_id_created_at', table_name='workspaces')
    op.drop_index('ix_workflow_runs_workflow_id_created_at', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_workflow_id_status', table_name='workflow_runs')
    op.drop_index('ix_workflows_workspace_id_created_at', table_name='workflows')
    op.drop_index('ix_documents_workspace_id_deleted_at', table_name='documents')
    op.drop_index('ix_documents_workspace_id_created_at', table_name='documents')
    op.drop_index('ix_documents_workspace_id_status', table_name='documents')
