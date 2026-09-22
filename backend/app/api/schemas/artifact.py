from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ArtifactVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    size_bytes: int
    created_at: datetime


class ArtifactSummary(BaseModel):
    """Enough to put a card in the transcript. Never the document — a poster in
    a chat bubble is four hundred lines of CSS nobody asked for."""

    id: UUID
    # The answer that made it, so a reload puts the card back where it was.
    message_id: UUID | None
    kind: str
    title: str
    version: int
    width: int
    height: int
    created_at: datetime


class ArtifactDetail(ArtifactSummary):
    html: str
    # What the frame is allowed to do, decided by the kind rather than by the
    # component. An empty string is the strongest setting there is.
    sandbox: str
    versions: list[ArtifactVersionSummary] = []


class ArtifactList(BaseModel):
    items: list[ArtifactSummary]
