from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ShareResponse(BaseModel):
    """The owner's view of their own link."""

    token: str
    # Built by the API rather than the browser, so the link someone copies is
    # the one the server would actually resolve.
    url: str
    title: str
    message_count: int
    view_count: int
    last_viewed_at: datetime | None
    created_at: datetime


class PublicMessage(BaseModel):
    role: str
    content: str
    created_at: datetime
    sources: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []


class PublicConversationResponse(BaseModel):
    """What a stranger with the link receives.

    No ids, no owner, no accounting. The model is the contract: anything not
    named here cannot be returned, whatever the snapshot happens to hold.
    """

    title: str
    messages: list[PublicMessage]
    shared_at: datetime
    message_count: int
