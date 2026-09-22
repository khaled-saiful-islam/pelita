"""An artifact and its versions.

Two tables rather than one. `artifacts` is the identity — what it is, who owns
it, which conversation it came from — and `artifact_versions` holds the
documents, one row per version.

Version is numbered **per artifact**, not per conversation. Keying it to the
conversation makes two different artifacts in one chat share a counter, so a
poster and a deck leapfrog each other's version numbers for no reason anybody
can explain later.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at, updated_at, uuid_pk


class Artifact(Base):
    """What was made. The document itself lives in a version row."""

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The assistant message that produced it, so the transcript can show a card
    # in the right place after a reload.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    versions: Mapped[list[ArtifactVersion]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
        order_by="ArtifactVersion.version",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_artifacts_conversation", "conversation_id", "created_at"),
        Index("ix_artifacts_user", "user_id", "created_at"),
        Index("ix_artifacts_message", "message_id"),
    )


class ArtifactVersion(Base):
    """One document. Immutable — an edit writes the next row, never over this
    one, so the version selector has something to select."""

    __tablename__ = "artifact_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    html: Mapped[str] = mapped_column(Text, nullable=False)
    # The direction this document was composed from. Kept so a palette change
    # is a substitution over known values rather than a fresh generation.
    design_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    build_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = created_at()

    artifact: Mapped[Artifact] = relationship(back_populates="versions")

    __table_args__ = (
        # Per artifact, which is the grain an edit increments.
        UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),
    )
