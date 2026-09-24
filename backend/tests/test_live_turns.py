"""A turn keeps running when the connection reading it goes away.

The behaviour these cover is the one that made leaving a build and coming back
show an empty conversation: the work was tied to the request, so the request
ending ended it. Everything here is about that seam — nothing calls a model.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from app.core.errors import ValidationError
from app.providers.base import FinishReason
from app.services.events import (
    ChatEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    StartEvent,
)
from app.services.live_turns import LiveTurns


def _start(conversation_id) -> StartEvent:
    return StartEvent(
        conversation_id=conversation_id,
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        title="A poster",
    )


async def _turn(conversation_id, gate: asyncio.Event) -> AsyncIterator[ChatEvent]:
    """A turn that says hello, waits to be released, then finishes."""
    yield _start(conversation_id)
    yield DeltaEvent(text="one")
    await gate.wait()
    yield DeltaEvent(text="two")
    yield DoneEvent(finish_reason=FinishReason.STOP)


@pytest.mark.asyncio
async def test_a_turn_carries_on_after_its_only_reader_leaves() -> None:
    turns, conversation, user = LiveTurns(), uuid4(), uuid4()
    gate = asyncio.Event()

    turn = turns.begin(user_id=user, source=_turn(conversation, gate))

    # One reader, which stops reading — the browser navigating away.
    reader = turn.follow()
    assert isinstance(await anext(reader), StartEvent)
    await reader.aclose()

    gate.set()
    await asyncio.wait_for(turn.task, timeout=2)

    said = [type(event).__name__ async for event in turn.follow()]
    assert said == ["StartEvent", "DeltaEvent", "DeltaEvent", "DoneEvent"]


@pytest.mark.asyncio
async def test_coming_back_replays_the_turn_from_the_beginning() -> None:
    turns, conversation, user = LiveTurns(), uuid4(), uuid4()
    gate = asyncio.Event()

    turns.begin(user_id=user, source=_turn(conversation, gate))
    await asyncio.sleep(0)  # let the turn open and register itself

    found = turns.find(conversation, user)
    assert found is not None

    # What a client arriving late sees: everything already said, not just what
    # happens next.
    first = await anext(found.follow())
    assert isinstance(first, StartEvent)

    gate.set()
    await asyncio.wait_for(found.task, timeout=2)


@pytest.mark.asyncio
async def test_two_readers_each_see_the_whole_turn() -> None:
    turns, conversation, user = LiveTurns(), uuid4(), uuid4()
    gate = asyncio.Event()
    turn = turns.begin(user_id=user, source=_turn(conversation, gate))

    async def read() -> list[str]:
        return [type(event).__name__ async for event in turn.follow()]

    both = asyncio.gather(read(), read())
    await asyncio.sleep(0)
    gate.set()
    one, two = await asyncio.wait_for(both, timeout=2)

    assert one == two
    assert one[0] == "StartEvent" and one[-1] == "DoneEvent"


@pytest.mark.asyncio
async def test_a_finished_turn_is_not_offered_again() -> None:
    """Its answer is in the database by then. Replaying it would draw a second
    copy of what is already on screen and count the cost twice."""
    turns, conversation, user = LiveTurns(), uuid4(), uuid4()
    gate = asyncio.Event()
    gate.set()

    turn = turns.begin(user_id=user, source=_turn(conversation, gate))
    await asyncio.wait_for(turn.task, timeout=2)

    assert turns.find(conversation, user) is None
    assert turns.running == 0


@pytest.mark.asyncio
async def test_somebody_elses_turn_is_not_found() -> None:
    turns, conversation = LiveTurns(), uuid4()
    gate = asyncio.Event()
    turns.begin(user_id=uuid4(), source=_turn(conversation, gate))
    await asyncio.sleep(0)

    assert turns.find(conversation, uuid4()) is None


@pytest.mark.asyncio
async def test_a_refused_turn_ends_as_an_error_event() -> None:
    """The refusal used to be an HTTP status. It cannot be one any more — the
    turn no longer runs inside the request — so it has to arrive as an event."""

    async def refuses() -> AsyncIterator[ChatEvent]:
        raise ValidationError("Message cannot be empty.")
        yield  # pragma: no cover - unreachable, makes this a generator

    turns = LiveTurns()
    turn = turns.begin(user_id=uuid4(), source=refuses())
    await asyncio.wait_for(turn.task, timeout=2)

    said = [event async for event in turn.follow()]
    assert isinstance(said[0], ErrorEvent)
    assert said[0].message == "Message cannot be empty."
    assert isinstance(said[1], DoneEvent)


@pytest.mark.asyncio
async def test_shutdown_stops_a_turn_nobody_will_ever_read() -> None:
    turns, conversation = LiveTurns(), uuid4()
    turn = turns.begin(user_id=uuid4(), source=_turn(conversation, asyncio.Event()))
    await asyncio.sleep(0)

    await asyncio.wait_for(turns.close_all(), timeout=2)

    assert turn.task is not None and turn.task.cancelled()
    assert turns.running == 0


@pytest.mark.asyncio
async def test_a_follower_does_not_sleep_through_an_event_that_lands_mid_check() -> None:
    """The bell is cleared before the re-check, never after. Cleared after, an
    event arriving in that window rings for nobody and the follower waits for a
    turn that has already moved on."""
    turns = LiveTurns()
    turn = turns.begin(user_id=uuid4(), source=_forever())

    reader = turn.follow()
    await anext(reader)  # drains what is there and settles into the wait

    for index in range(50):
        turn.append(DeltaEvent(text=str(index)))
        got = await asyncio.wait_for(anext(reader), timeout=1)
        assert isinstance(got, DeltaEvent)

    turn.close()
    await reader.aclose()
    await turns.close_all()


async def _forever() -> AsyncIterator[ChatEvent]:
    yield _start(uuid4())
    await asyncio.Event().wait()


# --- through the API ----------------------------------------------------


@pytest.fixture
def api(session):
    from app.api.deps import get_session, limit_auth
    from app.main import create_app

    app = create_app()

    async def _session():
        yield session

    async def _no_auth_limit() -> None:
        return None

    app.dependency_overrides[get_session] = _session
    # The sign-in limit is counted per address across the whole run, and these
    # sign in. Left on, they spend the budget `test_rate_limit.py` measures, and
    # that file fails in a full run while passing on its own -- which it did.
    app.dependency_overrides[limit_auth] = _no_auth_limit
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _signed_in(client, username: str = "tester") -> None:
    response = await client.post(
        "/api/auth/signin", json={"identifier": username, "password": "hunter2hunter2"}
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_following_a_conversation_with_nothing_running_is_an_empty_success(
    api, db_user
) -> None:
    """The ordinary case. Every conversation is asked about on the way in, and
    almost none of them have a turn in flight -- so not a 404, which a browser
    logs as a console error on every conversation opened."""
    async with api as client:
        await _signed_in(client)
        response = await client.get(f"/api/chat/live/{uuid4()}")

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_a_turn_cannot_be_followed_without_signing_in(api, db_user) -> None:
    async with api as client:
        response = await client.get(f"/api/chat/live/{uuid4()}")

    assert response.status_code == 401
