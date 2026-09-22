"""public links to an artifact

A frozen copy of one version, for the same reason conversation_shares is a
copy: a link that followed the artifact would republish every later edit
without the owner deciding to.

Revision ID: d4e7b21c9a55
Revises: c9a13f4d7e02
Create Date: 2026-09-22 11:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e7b21c9a55"
down_revision: str | None = "c9a13f4d7e02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_shares",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_artifact_shares_artifact", "artifact_shares", ["artifact_id"], unique=True)
    op.create_index("ix_artifact_shares_user", "artifact_shares", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_artifact_shares_user", table_name="artifact_shares")
    op.drop_index("ix_artifact_shares_artifact", table_name="artifact_shares")
    op.drop_table("artifact_shares")
