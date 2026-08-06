"""Add workflows and workflow_runs tables

Closes the schema drift where the initial migration (2c1d1be4d83d) never
created the workflow tables even though the SQLAlchemy models (and the old
runtime ``Base.metadata.create_all``) relied on them.

Uses ``CREATE TABLE IF NOT EXISTS`` because live databases may already contain
these tables from a prior ``create_all``-bootstrapped startup.

Revision ID: b3e7f2a5c901
Revises: 2c1d1be4d83d
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b3e7f2a5c901'
down_revision: Union[str, None] = '2c1d1be4d83d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS workflows (
            id UUID NOT NULL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            template_id VARCHAR(100) NOT NULL,
            status VARCHAR(20) NOT NULL,
            workspace_id UUID NOT NULL,
            created_by UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_workflows_workspace_id
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT fk_workflows_created_by
                FOREIGN KEY (created_by) REFERENCES users (id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id UUID NOT NULL PRIMARY KEY,
            workflow_id UUID NOT NULL,
            status VARCHAR(20) NOT NULL,
            input_json JSON,
            steps JSON,
            logs JSON,
            error TEXT,
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_workflow_runs_workflow_id
                FOREIGN KEY (workflow_id) REFERENCES workflows (id) ON DELETE CASCADE
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_runs")
    op.execute("DROP TABLE IF EXISTS workflows")
