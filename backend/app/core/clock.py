"""What time it is, where the person asking is.

A model knows roughly when its training ended and nothing at all about when it
is being asked, so left alone it takes its cutoff for today. Asked for the
current Premier League champion in September 2026, it read "2025/26 Arsenal" in
its own search results as a season still to come and answered with 2024-25 --
then searched the web for "today" when asked the date, and found a TV show.

The time is the one fact about the present that needs no search, so it is
simply given.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def zone(name: str | None, *, default: str = "UTC") -> tzinfo:
    """The named zone, else the default, else UTC.

    The name comes from the browser, so it is untrusted. `ZoneInfo` refuses a
    key that is an absolute path or climbs out of the zone database, and
    anything else it does not know is simply not a zone -- never an error that
    ends the turn over a clock.
    """
    for candidate in (name, default):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return UTC


def now_in(name: str | None, *, default: str = "UTC", clock: Clock = utc_now) -> datetime:
    return clock().astimezone(zone(name, default=default))


def describe(moment: datetime) -> str:
    """The moment as a person says it: "Thursday, 24 September 2026, 16:11
    (Asia/Kuala_Lumpur, UTC+08:00)".

    Day and month spelled out: "24/09/2026" is read as the 9th of the 24th
    month by somebody, and a model is somebody.
    """
    offset = moment.strftime("%z") or "+0000"
    signed = f"UTC{offset[:3]}:{offset[3:]}"
    name = getattr(moment.tzinfo, "key", None) or "UTC"
    return f"{moment:%A}, {moment.day} {moment:%B %Y, %H:%M} ({name}, {signed})"


def long_date(moment: datetime) -> str:
    """Just the day: "Thursday, 24 September 2026"."""
    return f"{moment:%A}, {moment.day} {moment:%B %Y}"
