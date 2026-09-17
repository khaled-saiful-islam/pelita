from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at, updated_at, uuid_pk

if TYPE_CHECKING:  # pragma: no cover
    from app.db.models.document import Document
    from app.db.models.source import MessageSource


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid_pk] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New chat")
    # ISO 639-1, detected from the first message. Null until then.
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        lazy="selectin",
    )

    __table_args__ = (
        # The sidebar query: one user's conversations, newest first.
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid_pk] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Null while a response is still streaming; set when it ends, including when
    # it ends because the user pressed stop.
    finish_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Accounting. usage_source records whether the provider reported these or
    # they were estimated, so a cost total never mixes the two silently.
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cost: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0, server_default="0"
    )
    usage_source: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = created_at()

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    # The element type is required. A bare `Mapped[list]` makes SQLAlchemy
    # treat this as a scalar, and assigning a list then fails with
    # "'list' object has no attribute '_sa_instance_state'" — after the answer
    # has already streamed, which kills the response mid-chunk.
    sources: Mapped[list[MessageSource]] = relationship(
        "MessageSource",
        cascade="all, delete-orphan",
        order_by="MessageSource.rank",
        lazy="selectin",
    )
    # Files sent with this message. Not cascaded: a file belongs to the
    # conversation and stays readable for the rest of it, so deleting the
    # message it arrived with must not take it away.
    documents: Mapped[list[Document]] = relationship(
        "Document",
        order_by="Document.created_at",
        lazy="selectin",
        viewonly=True,
    )

    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)
