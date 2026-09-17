"""Declarative base and column conventions shared by every model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at() -> Mapped[datetime]:
    """Creation time, from `clock_timestamp()` rather than `now()`.

    Postgres `now()` is the *transaction* start time and is identical for every
    row written in one transaction. A chat turn writes the question and the
    answer together, so with `now()` both carry the same timestamp and
    `ORDER BY created_at` returns them in an arbitrary order — which shows up as
    messages rendering out of sequence, and as "only the latest response can be
    regenerated" refusing the latest response.

    `clock_timestamp()` advances within a transaction, so insertion order is
    recoverable.
    """
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )


def updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
        onupdate=lambda: datetime.now(UTC),
    )
