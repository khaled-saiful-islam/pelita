"""documents

Revision ID: b3eef7130cb6
Revises: 18825a0b43c1
Create Date: 2026-09-17 11:36:39.042426
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'b3eef7130cb6'
down_revision: str | None = '18825a0b43c1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('media_type', sa.String(length=120), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('unit', sa.String(length=16), nullable=False),
    sa.Column('unit_count', sa.Integer(), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_documents_conversation', 'documents', ['conversation_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_documents_conversation', table_name='documents')
    op.drop_table('documents')
