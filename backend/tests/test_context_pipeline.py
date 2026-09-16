from __future__ import annotations

from uuid import uuid4

import pytest

from app.context.base import ContextContributor, StoredMessage, TurnContext, system
from app.context.contributors import (
    HistoryContributor,
    SystemPromptContributor,
    UserMessageContributor,
)
from app.context.pipeline import build_messages, trim_to_budget
from app.providers.base import ChatMessage, Role, TokenBudget


def make_ctx(**overrides) -> TurnContext:
    defaults = {
        "conversation_id": uuid4(),
        "user_id": uuid4(),
        "user_message": "what is the capital of Malaysia?",
        "model": "gpt-4o-mini",
        "history": (),
        "budget": TokenBudget(memory=512, tools=2048, history=4096),
    }
    return TurnContext(**{**defaults, **overrides})


DEFAULT_CONTRIBUTORS = (
    SystemPromptContributor("You are Pelita."),
    HistoryContributor(),
    UserMessageContributor(),
)


async def test_messages_come_out_in_registry_order() -> None:
    ctx = make_ctx(
        history=(
            StoredMessage(role=Role.USER, content="hi"),
            StoredMessage(role=Role.ASSISTANT, content="hello"),
        )
    )
    # Deliberately shuffled: order comes from the contributor, not the argument.
    shuffled = (DEFAULT_CONTRIBUTORS[2], DEFAULT_CONTRIBUTORS[0], DEFAULT_CONTRIBUTORS[1])
    messages, _ = await build_messages(ctx, shuffled)

    assert [m.role for m in messages] == [Role.SYSTEM, Role.USER, Role.ASSISTANT, Role.USER]
    assert messages[0].content == "You are Pelita."
    assert messages[-1].content == ctx.user_message


async def test_trace_records_every_contributor() -> None:
    ctx = make_ctx()
    _, trace = await build_messages(ctx, DEFAULT_CONTRIBUTORS)
    recorded = trace.as_dict()

    assert set(recorded) == {"system_prompt", "user_message"}
    assert recorded["user_message"]["messages"] == 1
    assert recorded["system_prompt"]["tokens"] > 0


async def test_a_failing_contributor_is_skipped_not_fatal() -> None:
    """Losing retrieved context should degrade an answer, not destroy the turn."""

    class Exploding(ContextContributor):
        name = "exploding"
        order = 150

        async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
            raise RuntimeError("vector store is down")

    messages, trace = await build_messages(make_ctx(), (*DEFAULT_CONTRIBUTORS, Exploding()))

    assert [m.role for m in messages] == [Role.SYSTEM, Role.USER]
    assert "exploding (failed)" in trace.as_dict()


async def test_new_contributor_slots_in_without_touching_others() -> None:
    """The template's central claim: adding a source is one class, one order."""

    class Retrieval(ContextContributor):
        name = "retrieval"
        order = 350

        async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
            return [system("Relevant document: Putrajaya is the administrative capital.")]

    ctx = make_ctx(history=(StoredMessage(role=Role.USER, content="earlier"),))
    messages, trace = await build_messages(ctx, (*DEFAULT_CONTRIBUTORS, Retrieval()))

    contents = [m.content for m in messages]
    assert contents.index("Relevant document: Putrajaya is the administrative capital.") == 1
    assert contents[2] == "earlier"
    assert "retrieval" in trace.as_dict()


async def test_empty_contributions_are_omitted() -> None:
    messages, trace = await build_messages(
        make_ctx(user_message="   "), (SystemPromptContributor(""), UserMessageContributor())
    )
    assert messages == ()
    assert trace.as_dict() == {}


async def test_history_drops_oldest_first_when_over_budget() -> None:
    history = tuple(
        StoredMessage(
            role=Role.USER if i % 2 == 0 else Role.ASSISTANT,
            content=f"turn {i} " + "x " * 60,
        )
        for i in range(10)
    )
    ctx = make_ctx(history=history, budget=TokenBudget(memory=0, tools=0, history=200))
    messages = await HistoryContributor().contribute(ctx)

    assert 0 < len(messages) < 10
    assert "turn 9" in messages[-1].content
    assert not any("turn 0" in m.content for m in messages)


async def test_history_skips_blank_messages() -> None:
    ctx = make_ctx(
        history=(
            StoredMessage(role=Role.USER, content="  "),
            StoredMessage(role=Role.ASSISTANT, content="kept"),
        )
    )
    messages = await HistoryContributor().contribute(ctx)
    assert [m.content for m in messages] == ["kept"]


@pytest.mark.parametrize("budget", [0, -10])
async def test_zero_budget_yields_nothing(budget: int) -> None:
    assert trim_to_budget([ChatMessage(role=Role.USER, content="hi")], budget, "gpt-4o-mini") == []


async def test_trim_never_splits_a_message() -> None:
    long_message = ChatMessage(role=Role.USER, content="word " * 500)
    kept = trim_to_budget([long_message], budget=10, model="gpt-4o-mini")
    assert kept == []


async def test_turn_context_is_immutable() -> None:
    ctx = make_ctx()
    with pytest.raises((AttributeError, TypeError)):
        ctx.user_message = "mutated"  # type: ignore[misc]
