"""guard events

Revision ID: 5e1f2a870258
Revises: 45cf5ac3aa9e
Create Date: 2026-09-17 09:23:02.299150
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '5e1f2a870258'
down_revision: str | None = '45cf5ac3aa9e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('guard_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('message_id', sa.UUID(), nullable=True),
    sa.Column('guard', sa.String(length=32), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('findings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_guard_events_created', 'guard_events', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_guard_events_created', table_name='guard_events')
    op.drop_table('guard_events')
