"""what an app remembers, per person

An app keeps what somebody typed into it -- tasks, names, a budget -- and that
is theirs, so it is keyed by user as well as artifact, and kept beside the
artifact rather than inside its document.

Revision ID: e8a3f61c2d95
Revises: d4e7b21c9a55
Create Date: 2026-09-24 14:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8a3f61c2d95"
down_revision: str | None = "d4e7b21c9a55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_states",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "user_id", name="uq_artifact_states_artifact_user"),
    )


def downgrade() -> None:
    op.drop_table("artifact_states")
