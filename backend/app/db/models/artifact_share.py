"""A public link to one artifact.

A frozen copy of one version, not a pointer at the live one — the same
reasoning as `conversation_shares`. A link that follows the artifact would
republish every later edit without the owner deciding to, and a copy written
before those edits existed cannot leak them however wrong a query is.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, uuid_pk


class ArtifactShare(Base):
    __tablename__ = "artifact_shares"

    id: Mapped[uuid.UUID] = uuid_pk()
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # The copy. Everything a stranger is given is in these four columns, so
    # what they can see is decided here rather than by a query somewhere else.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        # One link per artifact: re-sharing refreshes it rather than scattering
        # live links nobody can enumerate or revoke.
        Index("ix_artifact_shares_artifact", "artifact_id", unique=True),
        Index("ix_artifact_shares_user", "user_id"),
    )
