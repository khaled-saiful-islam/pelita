"""What an app remembers, for one person.

An app is the first artifact that holds data somebody typed into it: a task
list, the names on a spinner, a month's budget. That data is theirs, not the
app's, so it is keyed by who is using it as well as by what, and it lives
beside the artifact rather than inside its document -- a new version of the
app keeps the tasks, and a share link hands out the app without them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, updated_at, uuid_pk


class ArtifactState(Base):
    __tablename__ = "artifact_states"

    id: Mapped[uuid.UUID] = uuid_pk()
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Whatever the app saved. Opaque here: its shape is the app's business,
    # and the only rules that matter -- that it is JSON, and not too big --
    # are checked on the way in.
    data: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (
        # One row per app per person, overwritten rather than appended: this
        # is where the app is now, not a history of where it has been.
        UniqueConstraint("artifact_id", "user_id", name="uq_artifact_states_artifact_user"),
    )
