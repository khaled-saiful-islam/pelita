from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateMemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class UpdateMemoryRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=500)
    enabled: bool | None = None


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content: str
    # 'user' for something typed in settings, 'extracted' for something the
    # model proposed — people want to audit what was inferred about them.
    source: str
    enabled: bool
    created_at: datetime


class MemoryList(BaseModel):
    items: list[MemoryResponse]
    limit: int
