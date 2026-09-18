"""rate limit hits

One counter per (bucket, identity, window). In Postgres rather than in memory
because an in-process counter stops being a limit the moment there is a second
worker — it becomes the limit times the worker count, quietly.

Revision ID: e5b81c2f9d44
Revises: d17c4e9b5a30
Create Date: 2026-09-18 10:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5b81c2f9d44"
down_revision: str | None = "d17c4e9b5a30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_hits",
        sa.Column("bucket", sa.String(length=32), nullable=False),
        sa.Column("identity", sa.String(length=128), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("bucket", "identity", "window_start"),
    )
    op.create_index("ix_rate_limit_window", "rate_limit_hits", ["window_start"])


def downgrade() -> None:
    op.drop_index("ix_rate_limit_window", table_name="rate_limit_hits")
    op.drop_table("rate_limit_hits")
