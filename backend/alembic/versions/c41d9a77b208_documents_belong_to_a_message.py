"""documents belong to a message

Records which user message a file was sent with, so the transcript can show a
card at the point it was added rather than leaving it in the composer forever.

Nullable on purpose: a file is uploaded before there is a message to hang it
on, and that gap is the state the composer renders. Existing rows stay null —
files attached before this migration keep working, they just have no card.

ON DELETE SET NULL rather than CASCADE: a file belongs to the conversation and
stays readable for the rest of it, so deleting the message it arrived with must
not delete the file.

Revision ID: c41d9a77b208
Revises: b3eef7130cb6
Create Date: 2026-09-17 12:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c41d9a77b208"
down_revision: str | None = "b3eef7130cb6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("message_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_documents_message",
        "documents",
        "messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_documents_message", "documents", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_message", table_name="documents")
    op.drop_constraint("fk_documents_message", "documents", type_="foreignkey")
    op.drop_column("documents", "message_id")
