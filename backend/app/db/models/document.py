from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, uuid_pk


class Document(Base):
    """A file attached to a conversation, stored as the text we extracted.

    The extracted text is kept rather than the original bytes: it is what the
    model reads, it is a fraction of the size, and keeping user files on disk is
    a storage and retention problem a template should not hand anyone by
    default. The trade-off is that re-extracting with a better parser later
    means re-uploading.
    """

    __tablename__ = "documents"

    id: Mapped[uuid_pk] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # The user message this file was sent with. Null between the upload and the
    # next message — that gap is what the composer shows as a pending chip, and
    # what the transcript has not yet got a card for.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    # "page" for a PDF, "paragraph" for a docx, "line" for text — shown in the
    # UI so a two-page memo is distinguishable from a long report.
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="line")
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # A small JPEG data URI, for images only. Kept because a card showing a
    # filename and no picture is a poor answer to "did my photo upload?" — and
    # because the original bytes are not stored, so there is nothing else to
    # show. Bounded at upload; null for every other kind of file.
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        Index("ix_documents_conversation", "conversation_id", "created_at"),
        Index("ix_documents_message", "message_id"),
    )
