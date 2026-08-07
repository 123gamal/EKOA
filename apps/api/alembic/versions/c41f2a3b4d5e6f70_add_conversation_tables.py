"""Add conversations and messages tables

Implements Phase 4 conversation persistence: chat sessions scoped to a
workspace + organization and owned by the starting user, with per-turn
messages stored on the messages table so history survives across requests.

Revision ID: c41f2a3b4d5e6f70
Revises: b3e7f2a5c901
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c41f2a3b4d5e6f70'
down_revision: Union[str, None] = 'b3e7f2a5c901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id UUID NOT NULL PRIMARY KEY,
            title VARCHAR(255),
            workspace_id UUID NOT NULL,
            organization_id UUID NOT NULL,
            user_id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_conversations_workspace_id
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
            CONSTRAINT fk_conversations_organization_id
                FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE,
            CONSTRAINT fk_conversations_user_id
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id UUID NOT NULL PRIMARY KEY,
            conversation_id UUID NOT NULL,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_messages_conversation_id
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
        )
    """)
    op.create_index(
        'ix_conversations_workspace_user_created',
        'conversations',
        ['workspace_id', 'user_id', 'created_at'],
    )
    op.create_index(
        'ix_messages_conversation_id_created_at',
        'messages',
        ['conversation_id', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_messages_conversation_id_created_at', table_name='messages')
    op.drop_index('ix_conversations_workspace_user_created', table_name='conversations')
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS conversations")
