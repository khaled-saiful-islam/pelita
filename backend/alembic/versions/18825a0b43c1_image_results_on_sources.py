"""image results on sources

Revision ID: 18825a0b43c1
Revises: 7c3a91b4de20
Create Date: 2026-09-17 10:24:31.651663
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '18825a0b43c1'
down_revision: str | None = '7c3a91b4de20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('message_sources', sa.Column('thumbnail_url', sa.Text(), nullable=True))
    op.add_column('message_sources', sa.Column('image_url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('message_sources', 'image_url')
    op.drop_column('message_sources', 'thumbnail_url')
