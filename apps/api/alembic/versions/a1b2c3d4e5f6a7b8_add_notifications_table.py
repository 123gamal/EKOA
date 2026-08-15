"""Add notifications table

Phase 16 Part B-3: in-app notifications, event-driven (workflow
approval-needed, connector sync permanent failure).

Revision ID: a1b2c3d4e5f6a7b8
Revises: e4f5a6b7c9d0e1f2
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6a7b8'
down_revision: Union[str, None] = 'e4f5a6b7c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id UUID NOT NULL PRIMARY KEY,
            user_id UUID NOT NULL,
            organization_id UUID,
            type VARCHAR(50) NOT NULL,
            title VARCHAR(255) NOT NULL,
            body TEXT,
            resource_type VARCHAR(50),
            resource_id UUID,
            read_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_notifications_user_id
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            CONSTRAINT fk_notifications_organization_id
                FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE
        )
    """)
    op.create_index('ix_notifications_user_created', 'notifications', ['user_id', 'created_at'])
    op.create_index('ix_notifications_user_unread', 'notifications', ['user_id', 'read_at'])


def downgrade() -> None:
    op.drop_index('ix_notifications_user_unread', table_name='notifications')
    op.drop_index('ix_notifications_user_created', table_name='notifications')
    op.execute("DROP TABLE IF EXISTS notifications")
