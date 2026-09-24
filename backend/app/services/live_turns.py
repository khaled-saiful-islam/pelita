"""A turn that outlives the connection that asked for it.

A build takes minutes. Until now the turn was an async generator consumed
directly by the SSE response, so it lived and died with that one request:
reload the page, lose the connection, or have the browser suspend a
backgrounded socket, and the work stopped. Because an artifact is stored only
once it is finished, there was then nothing to come back to either — the
question was still there and the answer never arrived.

So the turn runs in its own task and writes what it emits into a buffer;
connections *subscribe*. A subscriber going away cancels the subscriber. Anyone
who asks again — the same tab after a reload, a second tab, the same tab
returning from another conversation — gets the turn replayed from its first
event and then follows it live.

In-process, like `CancellationRegistry` and for the same reason: a template
should not need Redis to be useful. That means one worker. To run several,
back `_turns` with a shared store and a pub/sub channel; nothing outside this
file knows how it works.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from app.core.errors import PelitaError
from app.providers.base import FinishReason
from app.services.events import ChatEvent, DoneEvent, ErrorEvent, StartEvent

logger = logging.getLogger(__name__)


class LiveTurn:
    """One running turn, and everything it has said so far.

    The buffer is the whole turn rather than a window: a turn is bounded by
    the answer it produces, and being able to hand a latecomer the beginning
    is the entire point.
    """

    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        # Both unknown until the turn opens: a brand-new conversation is given
        # its id by the first event.
        self.conversation_id: UUID | None = None
        self.assistant_message_id: UUID | None = None
        self.task: asyncio.Task[None] | None = None
        self._events: list[ChatEvent] = []
        self._bell = asyncio.Event()
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def append(self, event: ChatEvent) -> None:
        self._events.append(event)
        self._bell.set()

    def close(self) -> None:
        self._done = True
        self._bell.set()

    async def follow(self) -> AsyncIterator[ChatEvent]:
        """Everything said so far, then the rest as it is said."""
        seen = 0
        while True:
            while seen < len(self._events):
                yield self._events[seen]
                seen += 1
            if self._done:
                return
            # Cleared before the re-check, never after: an event that lands
            # between the drain and the clear would otherwise be rung for and
            # then wiped, and this follower would sleep through the rest of
            # the turn. Anything arriving after the clear rings again, so the
            # wait below returns immediately.
            self._bell.clear()
            if seen < len(self._events) or self._done:
                continue
            await self._bell.wait()


class LiveTurns:
    """The turns running right now, by conversation."""

    def __init__(self) -> None:
        self._turns: dict[UUID, LiveTurn] = {}
        # Held because asyncio keeps only a weak reference to a running task,
        # and a turn with no subscriber left would otherwise be collectable
        # mid-build.
        self._tasks: set[asyncio.Task[None]] = set()

    def begin(self, *, user_id: UUID, source: AsyncIterator[ChatEvent]) -> LiveTurn:
        """Start a turn. It runs whether or not anybody is listening."""
        turn = LiveTurn(user_id)
        task = asyncio.create_task(self._pump(turn, source))
        turn.task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return turn

    def find(self, conversation_id: UUID, user_id: UUID) -> LiveTurn | None:
        """The turn still running in this conversation, for its owner.

        A finished turn is deliberately not returned. Its answer is in the
        database by then, so replaying it would draw a second copy of
        something already on screen and charge the running total twice.
        """
        turn = self._turns.get(conversation_id)
        if turn is None or turn.done or turn.user_id != user_id:
            return None
        return turn

    async def _pump(self, turn: LiveTurn, source: AsyncIterator[ChatEvent]) -> None:
        try:
            async for event in source:
                if isinstance(event, StartEvent):
                    turn.conversation_id = event.conversation_id
                    turn.assistant_message_id = event.assistant_message_id
                    self._turns[event.conversation_id] = turn
                turn.append(event)
        except asyncio.CancelledError:
            raise
        except PelitaError as exc:
            # The response may already have begun, so an HTTP status is no
            # longer available anywhere. The reason arrives as an event.
            turn.append(ErrorEvent(message=exc.message))
            turn.append(DoneEvent(finish_reason=FinishReason.ERROR))
        except Exception:
            logger.exception("turn failed outside the stream")
            turn.append(
                ErrorEvent(message="Something went wrong generating the response.")
            )
            turn.append(DoneEvent(finish_reason=FinishReason.ERROR))
        finally:
            turn.close()
            known = turn.conversation_id
            if known is not None and self._turns.get(known) is turn:
                del self._turns[known]

    async def close_all(self) -> None:
        """Stop everything still running, on the way down.

        Without this a reload leaves the model being polled for an answer
        nobody can ever receive, and the process will not exit until it
        finishes.
        """
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def running(self) -> int:
        return len(self._turns)


# One registry per process, which matches the one-worker assumption above.
live_turns = LiveTurns()
