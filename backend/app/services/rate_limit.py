"""Request rate limiting.

Without this, one signed-in account can hold `/chat/stream` open in a loop and
spend the deployment's entire model budget before anyone notices. That is not a
hypothetical for a template people put on the public internet with their own API
key in `.env`.

Counted in Postgres so the limit survives more than one worker, and so a fork
needs no Redis to be safe.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import RateLimitError
from app.db.models.rate_limit import RateLimitHit

logger = logging.getLogger(__name__)

# Windows older than this are dead weight. Swept opportunistically rather than
# on a schedule, because a template should not need a cron to stay correct.
_SWEEP_AFTER = timedelta(hours=1)
_SWEEP_CHANCE = 0.01


@dataclass(frozen=True, slots=True)
class Limit:
    """A cap and the window it applies over."""

    requests: int
    seconds: int = 60

    @property
    def unlimited(self) -> bool:
        return self.requests <= 0


class RateLimiter:
    def __init__(self, session: AsyncSession, *, enabled: bool = True) -> None:
        self._session = session
        self._enabled = enabled

    async def check(self, bucket: str, identity: str, limit: Limit) -> None:
        """Count one request, raising once the window is full.

        The count happens before the work, so a refused request costs a row
        update rather than a model call.
        """
        if not self._enabled or limit.unlimited or not identity:
            return

        now = datetime.now(UTC)
        window_start = _floor(now, limit.seconds)

        statement = (
            insert(RateLimitHit)
            .values(bucket=bucket, identity=identity, window_start=window_start, count=1)
            .on_conflict_do_update(
                index_elements=["bucket", "identity", "window_start"],
                set_={"count": RateLimitHit.__table__.c.count + 1},
            )
            .returning(RateLimitHit.__table__.c.count)
        )
        # One statement, so two workers incrementing at once cannot both read
        # the same value and write the same total.
        used = int((await self._session.execute(statement)).scalar_one())

        # Committed here, before the request has done anything else. A refused
        # sign-in raises, the request session rolls back, and without this the
        # attempt un-counts itself — leaving the endpoint most worth limiting
        # as the one endpoint with no limit at all.
        await self._session.commit()

        if random.random() < _SWEEP_CHANCE:  # noqa: S311 - not security, just tidying
            await self._sweep(now)

        if used > limit.requests:
            window_end = window_start + timedelta(seconds=limit.seconds)
            retry_after = int((window_end - now).total_seconds())
            logger.info(
                "rate limit hit: bucket=%s identity=%s used=%d limit=%d",
                bucket,
                identity,
                used,
                limit.requests,
            )
            raise RateLimitError(
                f"Too many requests. Try again in {max(1, retry_after)} seconds.",
                retry_after=retry_after,
            )

    async def _sweep(self, now: datetime) -> None:
        await self._session.execute(
            delete(RateLimitHit).where(RateLimitHit.window_start < now - _SWEEP_AFTER)
        )


def _floor(moment: datetime, seconds: int) -> datetime:
    """The start of the window this moment falls in.

    Derived from the clock rather than from first use, so every worker agrees
    on where a window begins without coordinating.
    """
    epoch = int(moment.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC)
