from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.chat_service import MAX_MESSAGE_LENGTH


class SendMessageRequest(BaseModel):
    conversation_id: UUID | None = None
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    finish_reason: str | None
    model: str | None
    created_at: datetime


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageResponse]


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int
    limit: int
    offset: int
