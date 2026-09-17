"""The turn lifecycle, against a fake provider and a real database.

A fake provider rather than a mocked one: these tests are about what the service
does with a stream, and asserting on call arguments would test the wiring
instead of the behaviour.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.contributors import (
    HistoryContributor,
    SystemPromptContributor,
    UserMessageContributor,
)
from app.core.errors import NotFoundError, ValidationError
from app.db.models.conversation import Conversation, Message
from app.db.models.user import User
from app.providers.base import (
    ChatRequest,
    Completion,
    FinishReason,
    ProviderError,
    ProviderInfo,
    Role,
    TokenBudget,
    TokenEvent,
    Usage,
    UsageSource,
)
from app.services.cancellation import CancellationRegistry
from app.services.chat_service import ChatService, DeltaEvent, DoneEvent, ErrorEvent, StartEvent


class FakeProvider:
    """Emits the given chunks, optionally pausing so a stop can land mid-stream."""

    def __init__(self, chunks: list[str], *, delay: float = 0.0, fail: str | None = None) -> None:
        self._chunks = chunks
        self._delay = delay
        self._fail = fail
        self.received: ChatRequest | None = None
        self.info = ProviderInfo(name="fake", model="fake-model", base_url="http://fake")

    async def stream_chat(self, req: ChatRequest) -> AsyncIterator[TokenEvent]:
        self.received = req
        if self._fail:
            raise ProviderError(self._fail)
        for chunk in self._chunks:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield TokenEvent(text=chunk)

    async def complete(self, req: ChatRequest) -> Completion:
        return Completion(
            text="".join(self._chunks),
            usage=Usage(prompt_tokens=1, completion_tokens=1, source=UsageSource.ESTIMATED),
        )


def build_service(session: AsyncSession, provider, registry: CancellationRegistry) -> ChatService:
    @asynccontextmanager
    async def session_maker():
        # The test's session is already inside a rolled-back transaction, so
        # every "transaction" the service opens joins it and disappears after.
        yield session

    return ChatService(
        session_maker=session_maker,
        provider=provider,
        contributors=(
            SystemPromptContributor("You are Pelita."),
            HistoryContributor(),
            UserMessageContributor(),
        ),
        cancellation=registry,
        budget=TokenBudget(memory=256, tools=512, history=1024),
        max_tokens=256,
        temperature=0.5,
    )


@pytest.fixture
def registry() -> CancellationRegistry:
    return CancellationRegistry()


async def collect(service, **kwargs):
    return [event async for event in service.stream_turn(**kwargs)]


# --- a normal turn ------------------------------------------------------


async def test_a_turn_emits_start_tokens_then_done(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["Hel", "lo"]), registry)
    events = await collect(
        service, user_id=db_user.id, conversation_id=None, content="hello there"
    )

    assert isinstance(events[0], StartEvent)
    assert [e.text for e in events if isinstance(e, DeltaEvent)] == ["Hel", "lo"]
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].finish_reason is FinishReason.STOP


async def test_a_new_conversation_is_created_and_titled(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["ok"]), registry)
    events = await collect(
        service, user_id=db_user.id, conversation_id=None, content="Explain monsoons"
    )
    start = events[0]

    conversation = await session.get(Conversation, start.conversation_id)
    assert conversation is not None
    assert conversation.title == "Explain monsoons"


async def test_the_answer_is_persisted(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["a", "b", "c"]), registry)
    events = await collect(service, user_id=db_user.id, conversation_id=None, content="hi")

    stored = await session.get(Message, events[0].assistant_message_id)
    assert stored.content == "abc"
    assert stored.finish_reason == FinishReason.STOP


async def test_the_assistant_row_exists_before_any_token(session, db_user, registry) -> None:
    """Stop needs an id to address, and a mid-stream reload needs a row to find."""
    service = build_service(session, FakeProvider(["x"]), registry)
    stream = service.stream_turn(user_id=db_user.id, conversation_id=None, content="hi")

    start = await anext(stream)
    assert await session.get(Message, start.assistant_message_id) is not None

    async for _ in stream:
        pass


async def test_the_prompt_is_built_by_the_contributors(session, db_user, registry) -> None:
    provider = FakeProvider(["ok"])
    service = build_service(session, provider, registry)
    await collect(service, user_id=db_user.id, conversation_id=None, content="the question")

    roles = [m.role for m in provider.received.messages]
    assert roles == [Role.SYSTEM, Role.USER]
    assert provider.received.messages[0].content == "You are Pelita."
    assert provider.received.messages[-1].content == "the question"


async def test_history_reaches_the_second_turn(session, db_user, registry) -> None:
    provider = FakeProvider(["second"])
    service = build_service(session, provider, registry)

    first = await collect(service, user_id=db_user.id, conversation_id=None, content="first")
    cid = first[0].conversation_id
    await collect(service, user_id=db_user.id, conversation_id=cid, content="follow up")

    contents = [m.content for m in provider.received.messages]
    assert "first" in contents
    assert contents[-1] == "follow up"


# --- validation ---------------------------------------------------------


@pytest.mark.parametrize("content", ["", "   ", "\n\t"])
async def test_empty_messages_are_rejected(session, db_user, registry, content) -> None:
    service = build_service(session, FakeProvider(["x"]), registry)
    with pytest.raises(ValidationError, match="empty"):
        await collect(service, user_id=db_user.id, conversation_id=None, content=content)


async def test_overlong_messages_are_rejected(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["x"]), registry)
    with pytest.raises(ValidationError, match="too long"):
        await collect(
            service, user_id=db_user.id, conversation_id=None, content="x" * 32_001
        )


async def test_someone_elses_conversation_is_not_found(session, db_user, registry) -> None:
    stranger = User(
        username="stranger",
        email="stranger@example.com",
        password_hash="x",  # noqa: S106
        is_admin=False,
        is_active=True,
    )
    session.add(stranger)
    await session.flush()

    service = build_service(session, FakeProvider(["x"]), registry)
    theirs = await collect(
        service, user_id=stranger.id, conversation_id=None, content="private"
    )

    with pytest.raises(NotFoundError):
        await collect(
            service,
            user_id=db_user.id,
            conversation_id=theirs[0].conversation_id,
            content="peek",
        )


# --- failure ------------------------------------------------------------


async def test_a_provider_failure_becomes_an_error_event_not_an_exception(
    session, db_user, registry
) -> None:
    service = build_service(session, FakeProvider([], fail="upstream is down"), registry)
    events = await collect(service, user_id=db_user.id, conversation_id=None, content="hi")

    assert any(isinstance(e, ErrorEvent) and "upstream is down" in e.message for e in events)
    assert events[-1].finish_reason is FinishReason.ERROR


async def test_a_partial_answer_survives_a_provider_failure(session, db_user, registry) -> None:
    """Text the user watched appear should still be there after a reload."""

    class FailsHalfway(FakeProvider):
        async def stream_chat(self, req):
            self.received = req
            yield TokenEvent(text="the first half")
            raise ProviderError("died")

    service = build_service(session, FailsHalfway([]), registry)
    events = await collect(service, user_id=db_user.id, conversation_id=None, content="hi")

    stored = await session.get(Message, events[0].assistant_message_id)
    assert stored.content == "the first half"
    assert stored.finish_reason == FinishReason.ERROR


# --- cancellation -------------------------------------------------------


async def test_stopping_mid_stream_persists_the_partial(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(list("abcdefghij"), delay=0.02), registry)
    stream = service.stream_turn(user_id=db_user.id, conversation_id=None, content="count")

    start = await anext(stream)
    collected = []
    async for event in stream:
        if isinstance(event, DeltaEvent):
            collected.append(event.text)
            if len(collected) == 3:
                registry.cancel(start.assistant_message_id)
        if isinstance(event, DoneEvent):
            assert event.finish_reason is FinishReason.STOPPED

    assert len(collected) < 10
    stored = await session.get(Message, start.assistant_message_id)
    assert stored.content == "".join(collected)
    assert stored.finish_reason == FinishReason.STOPPED


async def test_stop_checks_ownership(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["x"]), registry)
    events = await collect(service, user_id=db_user.id, conversation_id=None, content="hi")

    with pytest.raises(NotFoundError):
        await service.stop(user_id=uuid4(), message_id=events[0].assistant_message_id)


async def test_stopping_an_unknown_message_is_not_found(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["x"]), registry)
    with pytest.raises(NotFoundError):
        await service.stop(user_id=db_user.id, message_id=uuid4())


async def test_the_registry_is_released_after_every_turn(session, db_user, registry) -> None:
    """A registry that only grows is a leak with a slow fuse."""
    service = build_service(session, FakeProvider(["x"]), registry)
    await collect(service, user_id=db_user.id, conversation_id=None, content="hi")
    assert registry.in_flight == 0


# --- regeneration -------------------------------------------------------


async def test_regeneration_reuses_the_row_with_new_content(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["first answer"]), registry)
    first = await collect(service, user_id=db_user.id, conversation_id=None, content="a question")
    assistant_id = first[0].assistant_message_id

    again = build_service(session, FakeProvider(["second answer"]), registry)
    second = await collect(
        again, user_id=db_user.id, conversation_id=None, regenerate_of=assistant_id
    )

    assert second[0].assistant_message_id == assistant_id
    stored = await session.get(Message, assistant_id)
    assert stored.content == "second answer"


async def test_regeneration_re_asks_the_original_question(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["ok"]), registry)
    first = await collect(
        service, user_id=db_user.id, conversation_id=None, content="the original question"
    )

    provider = FakeProvider(["ok"])
    again = build_service(session, provider, registry)
    await collect(
        again,
        user_id=db_user.id,
        conversation_id=None,
        regenerate_of=first[0].assistant_message_id,
    )

    assert provider.received.messages[-1].content == "the original question"


async def test_only_the_latest_answer_can_be_regenerated(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["one"]), registry)
    first = await collect(service, user_id=db_user.id, conversation_id=None, content="q1")
    cid = first[0].conversation_id
    await collect(service, user_id=db_user.id, conversation_id=cid, content="q2")

    with pytest.raises(ValidationError, match="latest response"):
        await collect(
            service,
            user_id=db_user.id,
            conversation_id=cid,
            regenerate_of=first[0].assistant_message_id,
        )


async def test_regenerating_an_unknown_message_is_not_found(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["x"]), registry)
    with pytest.raises(NotFoundError):
        await collect(
            service, user_id=db_user.id, conversation_id=None, regenerate_of=uuid4()
        )
