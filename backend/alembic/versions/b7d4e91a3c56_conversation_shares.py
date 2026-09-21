"""conversation shares

A public read-only copy of a conversation, frozen at the moment it was shared.

The snapshot is stored rather than the public view reading live messages: a
WHERE clause that filters out later messages is one bug away from not filtering
them, and a frozen copy cannot leak a message that did not exist when it was
written.

ON DELETE CASCADE from both conversations and users, so deleting either takes
the public link with it — a live URL pointing at a deleted conversation is the
worst failure this feature could have.

Revision ID: b7d4e91a3c56
Revises: a92f6c4b8e11
Create Date: 2026-09-18 14:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d4e91a3c56"
down_revision: str | None = "a92f6c4b8e11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_shares",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # One link per conversation: re-sharing refreshes it rather than
        # scattering live links nobody can enumerate or revoke.
        sa.UniqueConstraint("conversation_id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_shares_user", "conversation_shares", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_shares_user", table_name="conversation_shares")
    op.drop_table("conversation_shares")
