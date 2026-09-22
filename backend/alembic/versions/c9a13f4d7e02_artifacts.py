"""artifacts and their versions

An artifact is one self-contained HTML document. `artifacts` carries identity,
`artifact_versions` carries the documents — one row per version, unique on
(artifact_id, version) so numbering is per artifact rather than per
conversation. A conversation that produces a poster and then a deck should not
have them fighting over a shared counter.

ON DELETE CASCADE from conversations and users; SET NULL from messages, because
regenerating an answer replaces the message but the artifact it made is still
the user's.

Revision ID: c9a13f4d7e02
Revises: b7d4e91a3c56
Create Date: 2026-09-22 10:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9a13f4d7e02"
down_revision: str | None = "b7d4e91a3c56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artifacts_conversation", "artifacts", ["conversation_id", "created_at"])
    op.create_index("ix_artifacts_user", "artifacts", ["user_id", "created_at"])
    op.create_index("ix_artifacts_message", "artifacts", ["message_id"])

    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column(
            "design_spec",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("build_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),
    )


def downgrade() -> None:
    op.drop_table("artifact_versions")
    op.drop_index("ix_artifacts_message", table_name="artifacts")
    op.drop_index("ix_artifacts_user", table_name="artifacts")
    op.drop_index("ix_artifacts_conversation", table_name="artifacts")
    op.drop_table("artifacts")
