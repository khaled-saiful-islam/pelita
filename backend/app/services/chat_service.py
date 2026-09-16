"""The chat turn.

Orchestrates: persist the question, assemble the prompt from context
contributors, stream the answer, and persist whatever arrived — including when
the user stops it half way.

Transactions are short and explicit. A streaming response can stay open for
minutes, and holding a database transaction open for that long would pin a
connection and block migrations for as long as someone is reading an answer.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.context.base import ContextContributor, StoredMessage, TurnContext
from app.context.pipeline import build_messages
from app.core.errors import NotFoundError, ValidationError
from app.db.models.conversation import Conversation, Message
from app.db.repositories.conversations import SqlConversationRepository
from app.providers.base import (
    ChatRequest,
    FinishReason,
    LLMProvider,
    ProviderError,
    Role,
    TokenBudget,
    TokenEvent,
)
from app.services.cancellation import CancellationRegistry

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 32_000
HISTORY_MESSAGE_LIMIT = 50
TITLE_MAX_LENGTH = 60

SessionMaker = Callable[[], AbstractAsyncContextManager[AsyncSession]]


# --- events surfaced to the API layer -----------------------------------


@dataclass(frozen=True, slots=True)
class StartEvent:
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    title: str


@dataclass(frozen=True, slots=True)
class DeltaEvent:
    text: str


@dataclass(frozen=True, slots=True)
class DoneEvent:
    finish_reason: FinishReason


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    message: str


ChatEvent = StartEvent | DeltaEvent | DoneEvent | ErrorEvent


def derive_title(text: str) -> str:
    """A title from the first message, so a conversation is never called
    'New chat' in the sidebar while you are reading it."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= TITLE_MAX_LENGTH:
        return cleaned or "New chat"
    cut = cleaned[:TITLE_MAX_LENGTH]
    # Prefer a word boundary, but not one that leaves almost nothing.
    space = cut.rfind(" ")
    if space > TITLE_MAX_LENGTH // 2:
        cut = cut[:space]
    return cut.rstrip(",.;:!?-") + "…"


class ChatService:
    def __init__(
        self,
        *,
        session_maker: SessionMaker,
        provider: LLMProvider,
        contributors: tuple[ContextContributor, ...],
        cancellation: CancellationRegistry,
        budget: TokenBudget,
        max_tokens: int,
        temperature: float,
    ) -> None:
        self._session_maker = session_maker
        self._provider = provider
        self._contributors = contributors
        self._cancellation = cancellation
        self._budget = budget
        self._max_tokens = max_tokens
        self._temperature = temperature

    # -- public ----------------------------------------------------------

    async def stream_turn(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID | None,
        content: str,
    ) -> AsyncIterator[ChatEvent]:
        content = content.strip()
        if not content:
            raise ValidationError("Message cannot be empty.")
        if len(content) > MAX_MESSAGE_LENGTH:
            raise ValidationError(
                f"Message is too long ({len(content)} characters, limit {MAX_MESSAGE_LENGTH})."
            )

        start, history = await self._begin_turn(user_id, conversation_id, content)
        yield start

        assistant_id = start.assistant_message_id
        cancel = self._cancellation.register(assistant_id)
        collected: list[str] = []
        finish = FinishReason.STOP
        error: str | None = None

        try:
            turn = TurnContext(
                conversation_id=start.conversation_id,
                user_id=user_id,
                user_message=content,
                model=self._provider.info.model,
                history=history,
                budget=self._budget,
            )
            messages, trace = await build_messages(turn, self._contributors)
            logger.info("prompt assembled for %s: %s", assistant_id, trace.as_dict())

            request = ChatRequest(
                messages=messages,
                model=self._provider.info.model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stream=True,
            )

            async for event in self._provider.stream_chat(request):
                if cancel.is_set():
                    finish = FinishReason.STOPPED
                    break
                if isinstance(event, TokenEvent):
                    collected.append(event.text)
                    yield DeltaEvent(text=event.text)

        except ProviderError as exc:
            finish = FinishReason.ERROR
            error = exc.message
            logger.warning("provider failed during turn %s: %s", assistant_id, exc.message)
        except Exception:
            finish = FinishReason.ERROR
            error = "Something went wrong generating the response."
            logger.exception("unexpected failure during turn %s", assistant_id)
        finally:
            self._cancellation.release(assistant_id)
            # Persist whatever arrived, even on error or cancellation. A partial
            # answer the user watched appear should still be there on reload.
            await self._finish_turn(assistant_id, "".join(collected), finish)

        if error is not None:
            yield ErrorEvent(message=error)
        yield DoneEvent(finish_reason=finish)

    async def stop(self, *, user_id: UUID, message_id: UUID) -> bool:
        """Cancel an in-flight response. Ownership is checked first."""
        async with self._session_maker() as session:
            repo = SqlConversationRepository(session)
            message = await repo.get_message(message_id)
            if message is None:
                raise NotFoundError("No such message.")
            conversation = await repo.get(message.conversation_id, user_id)
            if conversation is None:
                raise NotFoundError("No such message.")
        return self._cancellation.cancel(message_id)

    # -- internals -------------------------------------------------------

    async def _begin_turn(
        self, user_id: UUID, conversation_id: UUID | None, content: str
    ) -> tuple[StartEvent, tuple[StoredMessage, ...]]:
        """Persist the question and reserve a row for the answer.

        The assistant row exists before a single token arrives so the stop
        endpoint has something to address and a reload mid-stream finds the
        turn rather than a gap.
        """
        async with self._session_maker() as session:
            repo = SqlConversationRepository(session)

            if conversation_id is None:
                conversation = await repo.create(user_id, derive_title(content))
            else:
                found = await repo.get(conversation_id, user_id)
                if found is None:
                    raise NotFoundError("No such conversation.")
                conversation = found
                if conversation.title == "New chat":
                    conversation.title = derive_title(content)

            history = await repo.recent_messages(
                conversation.id, limit=HISTORY_MESSAGE_LIMIT
            )

            user_message = await repo.add_message(
                Message(conversation_id=conversation.id, role=Role.USER, content=content)
            )
            assistant_message = await repo.add_message(
                Message(
                    conversation_id=conversation.id,
                    role=Role.ASSISTANT,
                    content="",
                    model=self._provider.info.model,
                )
            )
            await repo.touch(conversation)

            start = StartEvent(
                conversation_id=conversation.id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                title=conversation.title,
            )
            stored = tuple(
                StoredMessage(role=Role(m.role), content=m.content) for m in history
            )

        return start, stored

    async def _finish_turn(
        self, assistant_id: UUID, content: str, finish: FinishReason
    ) -> None:
        async with self._session_maker() as session:
            repo = SqlConversationRepository(session)
            message = await repo.get_message(assistant_id)
            if message is None:  # pragma: no cover - only if deleted mid-stream
                logger.warning("assistant message %s vanished before persist", assistant_id)
                return
            message.content = content
            message.finish_reason = finish


async def list_conversations(
    session: AsyncSession, user_id: UUID, *, limit: int, offset: int
) -> tuple[list[Conversation], int]:
    repo = SqlConversationRepository(session)
    return (
        await repo.list_for_user(user_id, limit=limit, offset=offset),
        await repo.count_for_user(user_id),
    )
