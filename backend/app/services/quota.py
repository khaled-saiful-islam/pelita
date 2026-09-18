"""Per-user token quotas.

Rate limiting caps how *often* someone asks; this caps how *much* they spend.
The two are different controls and both are needed: twenty short messages and
twenty long ones pass the same rate limit and cost very different money.

The window rolls. "In the last 24 hours" is what a person checking their own
usage expects, and it has no midnight at which a blocked account suddenly
unblocks and the whole allowance is spent again in an hour.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import RateLimitError
from app.db.models.conversation import Conversation, Message

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class Usage:
    """What an account has spent, and what it may spend."""

    tokens: int
    limit: int | None

    @property
    def unlimited(self) -> bool:
        return self.limit is None

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.tokens)

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.tokens >= self.limit


class TokenQuota:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def usage(self, user_id, limit: int | None) -> Usage:
        """Tokens this account has spent in the last 24 hours.

        Summed from the messages themselves rather than from a counter, so it
        stays true after a message is deleted and needs nothing kept in step.
        """
        since = datetime.now(UTC) - WINDOW
        total = await self._session.scalar(
            select(func.coalesce(func.sum(Message.prompt_tokens + Message.completion_tokens), 0))
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user_id, Message.created_at >= since)
        )
        return Usage(tokens=int(total or 0), limit=limit)

    async def check(self, user_id, limit: int | None) -> Usage:
        """Raise if the account is out of allowance, otherwise report it.

        Checked before the turn, not after: refusing costs a query, and letting
        it through costs whatever the model charges for a long answer.

        A turn is not refused part-way. Someone on their last hundred tokens
        gets a whole reply and ends up slightly over — stopping mid-sentence to
        save a fraction of a cent is a worse product than being approximate
        about the ceiling.
        """
        if limit is None:
            return Usage(tokens=0, limit=None)

        found = await self.usage(user_id, limit)
        if found.exhausted:
            logger.info(
                "token quota exhausted: user=%s used=%d limit=%d",
                user_id,
                found.tokens,
                limit,
            )
            raise RateLimitError(
                f"You have used your {limit:,}-token allowance for the last 24 hours "
                f"({found.tokens:,} used). It frees up as older messages age out.",
                # The window is rolling, so the real answer is "when your oldest
                # message passes 24 hours" — which needs another query to know.
                # An hour is an honest, cheap approximation to come back on.
                retry_after=3600,
            )
        return found
