from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.chat_service import MAX_MESSAGE_LENGTH


class SendMessageRequest(BaseModel):
    conversation_id: UUID | None = None
    content: str = Field(default="", max_length=MAX_MESSAGE_LENGTH)
    # When set, re-answers the question above this assistant message instead of
    # adding a new turn. `content` is ignored.
    regenerate_of: UUID | None = None


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    reason: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: UUID
    rating: str
    reason: str | None


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
    feedback: dict[UUID, FeedbackResponse] = {}


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int
    limit: int
    offset: int
