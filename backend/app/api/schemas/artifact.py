from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class ArtifactShareResponse(BaseModel):
    token: str
    url: str
    title: str
    version: int
    view_count: int
    created_at: datetime


class TextChange(BaseModel):
    """One run of words, by the number the browser and the server both give it."""

    index: int = Field(ge=0, le=5000)
    text: str = Field(max_length=2000)


class EditTextRequest(BaseModel):
    # Bounded because a poster has tens of runs, not thousands, and an
    # unbounded list is a way to spend a request handler's afternoon.
    changes: list[TextChange] = Field(max_length=200)


class ReviseRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=1000)


class AppState(BaseModel):
    """What an app saved. Its shape is the app's own; only its size is ours."""

    data: Any = Field(default=None, description="The app's saved data, as JSON.")
