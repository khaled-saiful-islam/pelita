"""document thumbnails

A small JPEG data URI for uploaded images, so the card in the transcript shows
the picture. Null for every other kind of file, and null for images uploaded
before this migration — the original bytes are not stored, so there is nothing
to backfill from.

Revision ID: d17c4e9b5a30
Revises: c41d9a77b208
Create Date: 2026-09-18 09:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d17c4e9b5a30"
down_revision: str | None = "c41d9a77b208"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("thumbnail", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "thumbnail")
