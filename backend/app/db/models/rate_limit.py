from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RateLimitHit(Base):
    """One counter per (bucket, identity, window).

    In Postgres rather than in memory, because an in-process counter is not a
    limit once there is more than one worker — it is a limit multiplied by the
    worker count, which is the same shape of bug as the stop button's
    `CancellationRegistry` and just as quiet.

    Fixed windows rather than a sliding log: one upsert per request against a
    primary key, no row per request to store or sweep. The cost is that a burst
    straddling a boundary can reach twice the limit briefly, which for
    protecting an API budget is a trade worth making.
    """

    __tablename__ = "rate_limit_hits"

    # "chat", "auth", "upload" — what is being limited.
    bucket: Mapped[str] = mapped_column(String(32), primary_key=True)
    # A user id, or an IP for endpoints reached before anyone is signed in.
    identity: Mapped[str] = mapped_column(String(128), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Only ever used to sweep expired windows.
    __table_args__ = (Index("ix_rate_limit_window", "window_start"),)
