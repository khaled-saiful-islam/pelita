from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, uuid_pk


class GuardEvent(Base):
    """A record of a guard firing.

    Persisted so the guard can be evaluated after the fact: a rule that fires
    constantly is probably wrong, and without a log the only evidence is people
    quietly turning the feature off.
    """

    __tablename__ = "guard_events"

    id: Mapped[uuid_pk] = uuid_pk()
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )

    guard: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    findings: Mapped[list] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = created_at()

    __table_args__ = (Index("ix_guard_events_created", "created_at"),)
