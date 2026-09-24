"""Today's date, in front of everything the model reads.

Order 150: after the system prompt, before memory and anything found this
turn, so the date is standing context -- the frame the rest is read in --
rather than one more fact among the search results.
"""

from __future__ import annotations

from datetime import datetime

from app.context.base import TurnContext, system
from app.core.clock import describe
from app.providers.base import ChatMessage

# Seasons that run across two years -- most football leagues, school and
# university years -- turn over in the northern summer.
SEASON_TURNS_IN_MONTH = 8


def anchors(now: datetime) -> str:
    """What today's date rules out, worked out rather than left to the model.

    Given "24 September 2026", a model still called the 2025/26 season one
    that "hasn't started yet". Arithmetic on dates is exactly what it is bad
    at and exactly what this can do for it.
    """
    year = now.year
    if now.month >= SEASON_TURNS_IN_MONTH:
        seasons = f"{_season(year - 1)} has finished and {_season(year)} is under way"
    else:
        seasons = f"{_season(year - 1)} is in its second half and {_season(year - 2)} has finished"
    return (
        f"So {year - 1} is over and {year} is under way; of the seasons that run "
        f"across two years, like a football league's, {seasons}."
    )


def _season(start: int) -> str:
    return f"{start}/{(start + 1) % 100:02d}"


def clock_note(now: datetime) -> str:
    return (
        f"It is now {describe(now)}. This comes from the system clock and is "
        "correct: use it whenever the date, the time, the day or the year matters, "
        "or anything described as current, latest or recent -- and never search "
        f"for it. {anchors(now)}\n\n"
        "Your training data stops well before today, so your sense of what is "
        "current is out of date: the latest season, champion, version, price or "
        "office holder you remember has probably changed since. For anything like "
        "that, rely on search results rather than memory, and say what date the "
        "information is from. If you cannot check, say it may have changed.\n\n"
        "When the person says you are wrong about a fact, do not agree or "
        "apologise before checking. Search, then say what the results show -- "
        "even when that means telling them, politely, that they are mistaken."
    )


class ClockContributor:
    name = "clock"
    order = 150

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
        if ctx.now is None:
            return []
        return [system(clock_note(ctx.now))]
