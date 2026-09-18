"""user token limits

A per-account cap on tokens spent in any rolling 24 hours. NULL is unlimited,
which is what every existing account gets: adding a limit to accounts that were
created without one would be a behaviour change dressed as a migration.

Revision ID: a92f6c4b8e11
Revises: e5b81c2f9d44
Create Date: 2026-09-18 11:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a92f6c4b8e11"
down_revision: str | None = "e5b81c2f9d44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("daily_token_limit", sa.Integer(), nullable=True))
    # The quota sums a user's messages over a window, which joins through
    # conversations. Without this that join is a sequential scan on every turn.
    op.create_index("ix_conversations_user", "conversations", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_user", table_name="conversations")
    op.drop_column("users", "daily_token_limit")
