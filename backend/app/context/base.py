"""Types crossing the context-contributor boundary.

A contributor is handed an immutable description of the turn and returns the
messages it wants in the prompt. It cannot see what other contributors produced
and cannot modify the turn, so the only way one contributor affects another is
through the ordering declared in the registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.providers.base import ChatMessage, Role, TokenBudget, ToolResult


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """A message already persisted in a conversation."""

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class AttachedDocument:
    """A file the user attached, as text the model can read."""

    id: UUID
    filename: str
    text: str
    unit: str
    unit_count: int


@dataclass(frozen=True, slots=True)
class TurnContext:
    """Everything a contributor is allowed to know about the current turn.

    Frozen on purpose. Contributors return new lists and never mutate this, so
    the prompt is a pure function of the turn plus the registry order.
    """

    conversation_id: UUID
    user_id: UUID
    user_message: str
    model: str
    history: tuple[StoredMessage, ...] = ()
    budget: TokenBudget = TokenBudget(memory=512, tools=2048, history=4096)
    # ISO 639-1 of the conversation, or None before detection has run.
    language: str | None = None
    # Output of any tools that ran for this turn (search, news, later RAG).
    tool_results: tuple[ToolResult, ...] = ()
    # Files attached to the conversation, oldest first.
    documents: tuple[AttachedDocument, ...] = ()
    # When the turn is happening, in the person's own zone. None only where a
    # caller has no clock, which is a test.
    now: datetime | None = None


@runtime_checkable
class ContextContributor(Protocol):
    """One source of prompt content.

    `order` decides position in the final message array. Leave gaps between
    registered values so a new contributor can be slotted in without renumbering
    the ones around it.
    """

    name: str
    order: int

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]: ...


def system(content: str) -> ChatMessage:
    return ChatMessage(role=Role.SYSTEM, content=content)


def user(content: str) -> ChatMessage:
    return ChatMessage(role=Role.USER, content=content)


def assistant(content: str) -> ChatMessage:
    return ChatMessage(role=Role.ASSISTANT, content=content)
