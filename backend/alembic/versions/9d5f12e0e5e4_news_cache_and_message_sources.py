"""news cache and message sources

Revision ID: 9d5f12e0e5e4
Revises: 022682f8be8f
Create Date: 2026-09-17 08:54:59.436161
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '9d5f12e0e5e4'
down_revision: str | None = '022682f8be8f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('news_cache',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('cache_key', sa.String(length=200), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_news_cache_cache_key'), 'news_cache', ['cache_key'], unique=True)
    op.create_table('message_sources',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('message_id', sa.UUID(), nullable=False),
    sa.Column('tool', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('snippet', sa.Text(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_message_sources_message', 'message_sources', ['message_id', 'rank'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_message_sources_message', table_name='message_sources')
    op.drop_table('message_sources')
    op.drop_index(op.f('ix_news_cache_cache_key'), table_name='news_cache')
    op.drop_table('news_cache')
