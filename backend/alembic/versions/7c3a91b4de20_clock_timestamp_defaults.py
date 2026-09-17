"""clock_timestamp defaults for ordering within a transaction

Revision ID: 7c3a91b4de20
Revises: 5e1f2a870258
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c3a91b4de20"
down_revision: str | None = "5e1f2a870258"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Postgres now() is the transaction start time, identical for every row written
# in one transaction. A chat turn writes the question and the answer together,
# so ORDER BY created_at over them was arbitrary. clock_timestamp() advances
# within a transaction, which makes insertion order recoverable.
TABLES = (
    ("users", ("created_at", "updated_at")),
    ("conversations", ("created_at", "updated_at")),
    ("messages", ("created_at",)),
    ("message_feedback", ("created_at", "updated_at")),
    ("memories", ("created_at", "updated_at")),
    ("news_cache", ("fetched_at",)),
    ("guard_events", ("created_at",)),
)


def upgrade() -> None:
    for table, columns in TABLES:
        for column in columns:
            op.alter_column(
                table, column, server_default=sa.text("clock_timestamp()")
            )


def downgrade() -> None:
    for table, columns in TABLES:
        for column in columns:
            op.alter_column(table, column, server_default=sa.text("now()"))
