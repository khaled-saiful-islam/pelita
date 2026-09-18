from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    # Null while the file is still in the composer; set to the user message it
    # was sent with, which is where the transcript renders its card.
    message_id: UUID | None = None
    filename: str
    media_type: str
    size_bytes: int
    # "page" for a PDF, "paragraph" for a docx, "line" for text.
    unit: str
    unit_count: int
    token_count: int
    # Set for images only — a data URI the card renders.
    thumbnail: str | None = None
    created_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentResponse]
    # Sent so the UI can state the rules before a file is picked, rather than
    # only after one is refused.
    max_files: int
    max_bytes: int
