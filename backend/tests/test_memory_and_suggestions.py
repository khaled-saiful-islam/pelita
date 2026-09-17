from __future__ import annotations

from uuid import uuid4

import pytest

from app.context.base import TurnContext
from app.context.contributors import MemoryContributor
from app.core.errors import NotFoundError, ValidationError
from app.providers.base import Role, TokenBudget
from app.services.memory_service import MemoryService, parse_facts
from app.services.suggestion_service import parse_suggestions

# --- parsing model output -----------------------------------------------
#
# Both services ask a model for a JSON array. Models wrap JSON in prose and
# fences however they like, so the array is located rather than assumed — and
# anything unparseable must yield nothing, because one of these writes to a
# user's profile.


@pytest.mark.parametrize(
    "raw",
    [
        '["one", "two"]',
        'Here you go:\n["one", "two"]',
        '```json\n["one", "two"]\n```',
        'Sure!\n\n```\n["one", "two"]\n```\nHope that helps.',
    ],
)
def test_arrays_are_found_however_they_are_wrapped(raw: str) -> None:
    assert parse_suggestions(raw, count=3) == ["one", "two"]
    assert parse_facts(raw) == ["one", "two"]


@pytest.mark.parametrize(
    "raw",
    ["", "no json here", "{}", "[unclosed", "null", '"a string"'],
)
def test_unparseable_output_yields_nothing(raw: str) -> None:
    assert parse_suggestions(raw, count=3) == []
    assert parse_facts(raw) == []


@pytest.mark.parametrize(
    "raw",
    ['{"items": ["a"]}', '{"suggestions": ["a"]}', '{"facts": ["a"], "note": "done"}'],
)
def test_an_array_wrapped_in_an_object_is_still_recovered(raw: str) -> None:
    """Models often answer {"items": [...]} despite being asked for a bare array.

    Locating the array recovers those instead of silently producing nothing,
    which is the difference between a feature that works on most providers and
    one that works on the one it was written against.
    """
    assert parse_suggestions(raw, count=3) == ["a"]
    assert parse_facts(raw) == ["a"]


def test_non_string_entries_are_dropped() -> None:
    assert parse_suggestions('["ok", 42, null, {"a": 1}]', count=3) == ["ok"]
    assert parse_facts('["ok", 42, null]') == ["ok"]


def test_suggestions_are_capped_and_deduplicated() -> None:
    raw = '["a", "A", "b", "c", "d"]'
    # "A" duplicates "a" case-insensitively, so four remain and three are taken.
    assert parse_suggestions(raw, count=3) == ["a", "b", "c"]


def test_long_suggestions_are_truncated() -> None:
    assert len(parse_suggestions(f'["{"x" * 300}"]', count=3)[0]) == 80


def test_whitespace_is_collapsed() -> None:
    assert parse_suggestions('["  spaced   out  "]', count=3) == ["spaced out"]


# --- the memory contributor ---------------------------------------------


def ctx(budget: int = 512) -> TurnContext:
    return TurnContext(
        conversation_id=uuid4(),
        user_id=uuid4(),
        user_message="hello",
        model="gpt-4o-mini",
        budget=TokenBudget(memory=budget, tools=2048, history=4096),
    )


async def test_no_memories_contributes_nothing() -> None:
    assert await MemoryContributor(()).contribute(ctx()) == []


async def test_memories_become_one_system_message() -> None:
    messages = await MemoryContributor(
        ("The user lives in Kuala Lumpur.", "The user is a backend engineer.")
    ).contribute(ctx())

    assert len(messages) == 1
    assert messages[0].role is Role.SYSTEM
    assert "Kuala Lumpur" in messages[0].content
    assert "backend engineer" in messages[0].content


async def test_memories_stop_at_the_token_budget() -> None:
    many = tuple(f"The user knows fact number {i} " + "x " * 50 for i in range(40))
    content = (await MemoryContributor(many).contribute(ctx(budget=120)))[0].content
    assert "fact number 0" in content
    assert "fact number 39" not in content


async def test_a_budget_too_small_for_even_one_fact_contributes_nothing() -> None:
    """A header with no facts under it is noise in the prompt."""
    assert await MemoryContributor(("x " * 200,)).contribute(ctx(budget=10)) == []


async def test_the_contributor_sits_between_the_system_prompt_and_tools() -> None:
    assert MemoryContributor().order == 200


# --- the service --------------------------------------------------------


@pytest.fixture
def service(session) -> MemoryService:
    return MemoryService(session, max_per_user=5)


async def test_a_memory_is_stored_and_listed(service, db_user) -> None:
    await service.add(db_user.id, "The user prefers short answers.")
    stored = await service.list_for(db_user.id)
    assert [m.content for m in stored] == ["The user prefers short answers."]
    assert stored[0].source == "user"
    assert stored[0].enabled is True


async def test_whitespace_is_normalised(service, db_user) -> None:
    memory = await service.add(db_user.id, "  The   user\n\nlikes tea.  ")
    assert memory.content == "The user likes tea."


@pytest.mark.parametrize("content", ["", "   ", "\n\t"])
async def test_empty_memories_are_rejected(service, db_user, content) -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        await service.add(db_user.id, content)


async def test_overlong_memories_are_rejected(service, db_user) -> None:
    with pytest.raises(ValidationError, match="500 characters"):
        await service.add(db_user.id, "x" * 501)


async def test_exact_duplicates_are_rejected(service, db_user) -> None:
    """A repeated fact adds nothing but tokens to every prompt."""
    await service.add(db_user.id, "The user likes tea.")
    with pytest.raises(ValidationError, match="already remembered"):
        await service.add(db_user.id, "the user likes TEA.")


async def test_the_per_user_limit_is_enforced(service, db_user) -> None:
    for i in range(5):
        await service.add(db_user.id, f"Fact number {i}.")
    with pytest.raises(ValidationError, match="limit of 5"):
        await service.add(db_user.id, "One too many.")


async def test_an_invalid_source_is_rejected(service, db_user) -> None:
    with pytest.raises(ValidationError, match="'user' or 'extracted'"):
        await service.add(db_user.id, "A fact.", source="somewhere-else")


async def test_editing_changes_the_content(service, db_user) -> None:
    memory = await service.add(db_user.id, "The user likes tea.")
    updated = await service.update(db_user.id, memory.id, content="The user likes coffee.")
    assert updated.content == "The user likes coffee."


async def test_disabling_keeps_the_row_but_drops_it_from_the_prompt(service, db_user) -> None:
    """"Stop using this" should not have to mean "delete it"."""
    memory = await service.add(db_user.id, "The user likes tea.")
    await service.update(db_user.id, memory.id, enabled=False)

    assert len(await service.list_for(db_user.id)) == 1
    assert await service.list_for(db_user.id, enabled_only=True) == []


async def test_deleting_removes_it(service, db_user) -> None:
    memory = await service.add(db_user.id, "The user likes tea.")
    await service.delete(db_user.id, memory.id)
    assert await service.list_for(db_user.id) == []


async def test_another_users_memory_is_not_found(service, db_user) -> None:
    memory = await service.add(db_user.id, "The user likes tea.")
    with pytest.raises(NotFoundError):
        await service.update(uuid4(), memory.id, content="hacked")
    with pytest.raises(NotFoundError):
        await service.delete(uuid4(), memory.id)


async def test_an_unknown_memory_is_not_found(service, db_user) -> None:
    with pytest.raises(NotFoundError):
        await service.delete(db_user.id, uuid4())


async def test_extraction_failure_returns_nothing_rather_than_raising(service) -> None:
    """Extraction must never affect the conversation it came from."""

    class Broken:
        info = type("I", (), {"model": "m"})()

        async def complete(self, req):
            raise RuntimeError("provider down")

    assert await service.extract(Broken(), user_message="hi", assistant_message="hello") == []
