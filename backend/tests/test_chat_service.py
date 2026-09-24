"""The turn lifecycle, against a fake provider and a real database.

A fake provider rather than a mocked one: these tests are about what the service
does with a stream, and asserting on call arguments would test the wiring
instead of the behaviour.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.clock import ClockContributor
from app.context.contributors import (
    HistoryContributor,
    MemoryContributor,
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
    StreamEvent,
    TokenBudget,
    TokenEvent,
    ToolCall,
    ToolCallsEvent,
    Usage,
    UsageSource,
)
from app.services.accounting_service import Pricing
from app.services.cancellation import CancellationRegistry
from app.services.chat_service import ChatService, TurnSettings
from app.services.events import (
    AccountingEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    StartEvent,
    SuggestionsEvent,
)


class FakeProvider:
    """Emits the given chunks, optionally pausing so a stop can land mid-stream."""

    def __init__(
        self,
        chunks: list[str],
        *,
        delay: float = 0.0,
        fail: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        supports_tools: bool = True,
    ) -> None:
        self._chunks = chunks
        self._delay = delay
        self._fail = fail
        # Asked for on the first pass only, exactly as a real model does: it
        # requests tools, reads the results, then answers.
        self._tool_calls = tool_calls or []
        self.received: ChatRequest | None = None
        self.requests: list[ChatRequest] = []
        self.info = ProviderInfo(
            name="fake",
            model="fake-model",
            base_url="http://fake",
            supports_tools=supports_tools,
        )

    async def stream_chat(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.received = req
        self.requests.append(req)
        if self._fail:
            raise ProviderError(self._fail)

        if self._tool_calls and req.tools:
            calls = tuple(self._tool_calls)
            self._tool_calls = []
            yield ToolCallsEvent(calls=calls)
            return

        for chunk in self._chunks:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield TokenEvent(text=chunk)

    async def complete(self, req: ChatRequest) -> Completion:
        return Completion(
            text="".join(self._chunks),
            usage=Usage(prompt_tokens=1, completion_tokens=1, source=UsageSource.ESTIMATED),
        )


def build_service(
    session: AsyncSession,
    provider,
    registry: CancellationRegistry,
    *,
    memories_in_prompt: bool = False,
    suggestions: bool = False,
    extract: bool = False,
    tools: dict | None = None,
    tool_calling: bool = False,
    clock=None,
    guards: tuple = (),
) -> ChatService:
    @asynccontextmanager
    async def session_maker():
        # The test's session is already inside a rolled-back transaction, so
        # every "transaction" the service opens joins it and disappears after.
        yield session

    def contributors(memories: tuple[str, ...]):
        return (
            SystemPromptContributor("You are Pelita."),
            # Only when a test fixes the time: the rest assert on prompts that
            # would otherwise carry whatever the real clock said.
            *((ClockContributor(),) if clock else ()),
            *((MemoryContributor(memories),) if memories_in_prompt else ()),
            HistoryContributor(),
            UserMessageContributor(),
        )

    return ChatService(
        session_maker=session_maker,
        provider=provider,
        contributor_factory=contributors,
        cancellation=registry,
        tools=tools,
        guards=guards,
        **({"clock": clock} if clock else {}),
        settings=TurnSettings(
            budget=TokenBudget(memory=256, tools=512, history=1024),
            pricing=Pricing(
                input_per_1m=Decimal("0.15"), output_per_1m=Decimal("0.60"), currency="USD"
            ),
            max_tokens=256,
            temperature=0.5,
            supported_languages=("en", "ms", "ta", "zh", "bn"),
            default_language="en",
            # Off by default so most tests exercise one provider call and assert
            # on the turn rather than on the follow-up work that trails it.
            suggestions_enabled=suggestions,
            memory_auto_extract=extract,
            memory_max_per_user=100,
            # Off by default: most tests are about the turn, and the fallback
            # path keeps them to one provider call. The tool-calling tests turn
            # it on explicitly.
            tool_calling_enabled=tool_calling,
        ),
    )


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
    assert any(isinstance(e, AccountingEvent) for e in events)


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
    # The system message carries the base prompt plus the detected-language
    # instruction, in that order.
    assert provider.received.messages[0].content.startswith("You are Pelita.")
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


# --- accounting ---------------------------------------------------------


async def test_every_turn_reports_usage(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["some answer"]), registry)
    events = await collect(service, user_id=db_user.id, conversation_id=None, content="hi there")

    accounting = next(e.accounting for e in events if isinstance(e, AccountingEvent))
    assert accounting.completion_tokens > 0
    assert accounting.currency == "USD"


async def test_usage_is_estimated_when_the_provider_reports_none(
    session, db_user, registry
) -> None:
    """The fake provider sends no usage block, like Ollama and some vLLM builds."""
    service = build_service(session, FakeProvider(["answer"]), registry)
    events = await collect(service, user_id=db_user.id, conversation_id=None, content="hi there")

    accounting = next(e.accounting for e in events if isinstance(e, AccountingEvent))
    assert accounting.source is UsageSource.ESTIMATED


async def test_accounting_is_persisted_on_the_message(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["answer"]), registry)
    events = await collect(service, user_id=db_user.id, conversation_id=None, content="hi there")

    stored = await session.get(Message, events[0].assistant_message_id)
    assert stored.completion_tokens > 0
    assert stored.usage_source == UsageSource.ESTIMATED


async def test_a_cancelled_turn_is_still_priced(session, db_user, registry) -> None:
    """Tokens consumed before the stop were still paid for."""
    service = build_service(session, FakeProvider(list("abcdefghij"), delay=0.02), registry)
    stream = service.stream_turn(user_id=db_user.id, conversation_id=None, content="count to ten")

    start = await anext(stream)
    events = []
    async for event in stream:
        events.append(event)
        if isinstance(event, DeltaEvent) and len(events) == 3:
            registry.cancel(start.assistant_message_id)

    accounting = next(e.accounting for e in events if isinstance(e, AccountingEvent))
    assert accounting.prompt_tokens > 0


# --- language -----------------------------------------------------------


async def test_the_language_is_detected_and_stored(session, db_user, registry) -> None:
    service = build_service(session, FakeProvider(["jawapan"]), registry)
    events = await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="Terangkan bagaimana angin monsun berfungsi di Asia Tenggara",
    )

    assert events[0].language == "ms"
    conversation = await session.get(Conversation, events[0].conversation_id)
    assert conversation.language == "ms"


async def test_the_language_reaches_the_system_prompt(session, db_user, registry) -> None:
    provider = FakeProvider(["ok"])
    service = build_service(session, provider, registry)
    await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="Terangkan bagaimana angin monsun berfungsi di Asia Tenggara",
    )

    assert "Bahasa Melayu" in provider.received.messages[0].content


async def test_the_language_is_detected_once_not_per_turn(session, db_user, registry) -> None:
    """Re-detecting every turn would flip the reply language on a short "ok"."""
    service = build_service(session, FakeProvider(["ok"]), registry)
    first = await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="Terangkan bagaimana angin monsun berfungsi di Asia Tenggara",
    )
    cid = first[0].conversation_id

    second = await collect(service, user_id=db_user.id, conversation_id=cid, content="ok thanks")
    assert second[0].language == "ms"


# --- memory and suggestions in the turn ---------------------------------


async def test_enabled_memories_reach_the_prompt(session, db_user, registry) -> None:
    from app.services.memory_service import MemoryService

    memories = MemoryService(session)
    await memories.add(db_user.id, "The user lives in Kuala Lumpur.")

    provider = FakeProvider(["ok"])
    service = build_service(session, provider, registry, memories_in_prompt=True)
    await collect(service, user_id=db_user.id, conversation_id=None, content="where am I?")

    prompt = " ".join(m.content for m in provider.received.messages)
    assert "Kuala Lumpur" in prompt


async def test_disabled_memories_do_not_reach_the_prompt(session, db_user, registry) -> None:
    from app.services.memory_service import MemoryService

    memories = MemoryService(session)
    memory = await memories.add(db_user.id, "The user lives in Kuala Lumpur.")
    await memories.update(db_user.id, memory.id, enabled=False)

    provider = FakeProvider(["ok"])
    service = build_service(session, provider, registry, memories_in_prompt=True)
    await collect(service, user_id=db_user.id, conversation_id=None, content="where am I?")

    prompt = " ".join(m.content for m in provider.received.messages)
    assert "Kuala Lumpur" not in prompt


async def test_suggestions_are_emitted_after_a_clean_finish(session, db_user, registry) -> None:
    class WithSuggestions(FakeProvider):
        async def complete(self, req):
            return Completion(
                text='["First follow-up?", "Second follow-up?"]',
                usage=Usage(prompt_tokens=1, completion_tokens=1, source=UsageSource.ESTIMATED),
            )

    service = build_service(session, WithSuggestions(["answer"]), registry, suggestions=True)
    events = await collect(service, user_id=db_user.id, conversation_id=None, content="a question")

    chips = next(e.items for e in events if isinstance(e, SuggestionsEvent))
    assert chips == ("First follow-up?", "Second follow-up?")


async def test_no_suggestions_after_a_cancelled_answer(session, db_user, registry) -> None:
    """Following up on a half-written answer wastes a call and reads as the app
    not noticing it was stopped."""
    service = build_service(
        session, FakeProvider(list("abcdefghij"), delay=0.02), registry, suggestions=True
    )
    stream = service.stream_turn(user_id=db_user.id, conversation_id=None, content="count")

    start = await anext(stream)
    events = []
    async for event in stream:
        events.append(event)
        if isinstance(event, DeltaEvent) and len(events) == 2:
            registry.cancel(start.assistant_message_id)

    assert not any(isinstance(e, SuggestionsEvent) for e in events)
