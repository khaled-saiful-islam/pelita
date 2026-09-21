from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, uuid_pk


class ConversationShare(Base):
    """A public, read-only copy of a conversation at one moment.

    The snapshot is stored rather than the public view reading the live
    conversation, and that is the whole security design. A `WHERE` clause that
    filters out later messages is one bug away from not filtering them; a frozen
    copy cannot leak a message that did not exist when it was written. What the
    owner reviewed before sharing is exactly and permanently what is public.

    It also means regenerating an old answer does not silently change what
    strangers can read, and revoking is deleting one row.
    """

    __tablename__ = "conversation_shares"

    id: Mapped[uuid_pk] = uuid_pk()
    # One link per conversation: re-sharing refreshes this row rather than
    # scattering live links nobody can enumerate or revoke.
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Denormalised so ownership can be checked without loading the conversation,
    # and so deleting an account takes its links with it even if a conversation
    # somehow outlives it.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 256 bits of urandom. The URL is the credential, so it has to be long
    # enough that guessing is not a strategy.
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # An allow-listed copy of the messages. Never the whole row.
    snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # So the owner can see the link is being used, and stop it if not.
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = created_at()

    __table_args__ = (Index("ix_shares_user", "user_id"),)
