from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, updated_at, uuid_pk


class MessageFeedback(Base):
    """A thumbs up or down on one assistant message.

    One row per user per message — rating again updates rather than appends, so
    the table answers "what does this person think of this answer now?" rather
    than "what have they clicked over time".
    """

    __tablename__ = "message_feedback"

    id: Mapped[uuid_pk] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    rating: Mapped[str] = mapped_column(String(8), nullable=False)  # up | down
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_feedback_message_user"),)
