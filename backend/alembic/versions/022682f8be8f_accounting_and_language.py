"""accounting and language

Revision ID: 022682f8be8f
Revises: 43840d574e7d
Create Date: 2026-09-17 08:44:40.690341
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '022682f8be8f'
down_revision: str | None = '43840d574e7d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('language', sa.String(length=8), nullable=True))
    # server_default is required: these are NOT NULL and the table already has
    # rows, which would otherwise fail on every existing installation.
    op.add_column(
        'messages',
        sa.Column('prompt_tokens', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'messages',
        sa.Column('completion_tokens', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'messages',
        sa.Column(
            'cost', sa.Numeric(precision=12, scale=6), nullable=False, server_default='0'
        ),
    )
    op.add_column('messages', sa.Column('usage_source', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'usage_source')
    op.drop_column('messages', 'cost')
    op.drop_column('messages', 'completion_tokens')
    op.drop_column('messages', 'prompt_tokens')
    op.drop_column('conversations', 'language')
