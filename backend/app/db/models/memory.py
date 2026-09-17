from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, updated_at, uuid_pk


class Memory(Base):
    """A fact about the user, injected into the system prompt.

    `source` records where it came from — 'user' for something typed in
    settings, 'extracted' for something the model proposed. Keeping them
    distinguishable matters: people trust what they wrote themselves and want to
    audit what was inferred about them.
    """

    __tablename__ = "memories"

    id: Mapped[uuid_pk] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    # Off keeps the row but leaves it out of the prompt, so "stop using this"
    # does not have to mean "delete it".
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (Index("ix_memories_user_created", "user_id", "created_at"),)
