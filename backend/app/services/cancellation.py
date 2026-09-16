"""Server-side cancellation for in-flight responses.

The stop button has to do more than close the browser's connection. If it only
did that, the server would keep pulling tokens from the model and keep paying
for them, and the partial answer would be lost. So stopping is an explicit
request that flips an event the streaming loop is watching.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

logger = logging.getLogger(__name__)


class CancellationRegistry:
    """Tracks which in-flight messages have been asked to stop.

    In-process, which means one API worker. That is a deliberate limit for a
    template rather than an oversight: the alternative is a Redis dependency
    that most people cloning this will never need. To run multiple workers,
    replace this class with one backed by a shared store — the interface is
    three methods and nothing outside this file knows how it works.
    """

    def __init__(self) -> None:
        self._events: dict[UUID, asyncio.Event] = {}

    def register(self, message_id: UUID) -> asyncio.Event:
        event = asyncio.Event()
        self._events[message_id] = event
        return event

    def cancel(self, message_id: UUID) -> bool:
        """Return whether there was anything to cancel."""
        event = self._events.get(message_id)
        if event is None:
            return False
        event.set()
        logger.info("cancellation requested for message %s", message_id)
        return True

    def release(self, message_id: UUID) -> None:
        """Always call this when a stream ends, however it ends."""
        self._events.pop(message_id, None)

    def is_cancelled(self, message_id: UUID) -> bool:
        event = self._events.get(message_id)
        return event is not None and event.is_set()

    @property
    def in_flight(self) -> int:
        return len(self._events)


# One registry per process, which matches the one-worker assumption above.
registry = CancellationRegistry()
