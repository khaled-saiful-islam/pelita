from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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
    # Run a web search before answering. Ignored when SERPAPI_KEY is unset.
    use_search: bool = False


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


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    title: str
    url: str
    snippet: str


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    finish_reason: str | None
    model: str | None
    created_at: datetime
    prompt_tokens: int
    completion_tokens: int
    cost: Decimal
    usage_source: str | None
    sources: list[SourceResponse] = []


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    language: str | None
    created_at: datetime
    updated_at: datetime


class ConversationTotals(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: Decimal
    currency: str
    # True when any message in the conversation was priced from an estimate, so
    # the UI can say the total is approximate rather than implying precision.
    estimated: bool


class ConversationDetail(ConversationSummary):
    messages: list[MessageResponse]
    feedback: dict[UUID, FeedbackResponse] = {}
    totals: ConversationTotals


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int
    limit: int
    offset: int
