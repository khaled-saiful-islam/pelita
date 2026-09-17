from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, uuid_pk


class MessageSource(Base):
    """A citation attached to an assistant message.

    Persisted rather than held in the stream, so the sources under an answer are
    still there after a reload — an answer you cannot check is worth less than
    one you can.
    """

    __tablename__ = "message_sources"

    id: Mapped[uuid_pk] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )

    tool: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Set only for image-search results, so a reloaded conversation still
    # shows the pictures rather than a list of bare links.
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_message_sources_message", "message_id", "rank"),)
