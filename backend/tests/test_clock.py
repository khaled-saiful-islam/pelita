"""The model is told what time it is, where the person is.

The regression this guards: asked for the current Premier League champion on
24 September 2026, the model read "2025/26 Arsenal" in its own search results
as the future and answered with the 2024-25 season, then searched the web for
"today" when asked the date. Nothing had told it when now was.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.context.base import TurnContext
from app.context.clock import ClockContributor, anchors
from app.context.registry import build_contributors
from app.core.clock import describe, now_in, zone

SEPT_24 = datetime(2026, 9, 24, 8, 11, tzinfo=UTC)


def ctx(now: datetime | None) -> TurnContext:
    return TurnContext(
        conversation_id=uuid4(),
        user_id=uuid4(),
        user_message="who is the current EPL champion?",
        model="gpt-4o-mini",
        now=now,
    )


def test_the_moment_is_given_in_the_persons_own_zone() -> None:
    moment = now_in("Asia/Kuala_Lumpur", clock=lambda: SEPT_24)
    assert (moment.hour, moment.minute) == (16, 11)
    assert moment.utcoffset().total_seconds() == 8 * 3600


def test_an_unknown_zone_falls_back_to_the_default() -> None:
    assert (
        now_in("Mars/Olympus_Mons", default="Asia/Kuala_Lumpur", clock=lambda: SEPT_24).hour == 16
    )


def test_a_zone_that_is_a_path_is_refused_not_opened() -> None:
    assert zone("../../etc/passwd", default="") is UTC
    assert zone("/etc/localtime", default="") is UTC


def test_no_zone_and_no_default_is_utc() -> None:
    assert zone(None, default="") is UTC


def test_the_description_is_a_date_a_person_would_say() -> None:
    said = describe(now_in("Asia/Kuala_Lumpur", clock=lambda: SEPT_24))
    assert "Thursday, 24 September 2026" in said
    assert "16:11" in said
    assert "Asia/Kuala_Lumpur" in said
    assert "UTC+08:00" in said


async def test_the_model_is_told_the_date_and_not_to_search_for_it() -> None:
    [message] = await ClockContributor().contribute(ctx(now_in("UTC", clock=lambda: SEPT_24)))
    assert "Thursday, 24 September 2026" in message.content
    assert "never search for it" in message.content
    # The half that fixes the stale-season answer: its memory is not "now".
    assert "out of date" in message.content


async def test_no_moment_means_nothing_is_said() -> None:
    assert await ClockContributor().contribute(ctx(None)) == []


def test_the_clock_comes_right_after_the_system_prompt() -> None:
    orders = {c.name: c.order for c in build_contributors()}
    assert orders["system_prompt"] < orders["clock"] < orders["memory"]


# --- what "now" rules out ------------------------------------------------
#
# Told the date was 24 September 2026, the model still said the 2025/26
# season "hasn't started yet". The arithmetic is done for it.


def test_after_the_summer_the_split_season_that_ended_is_named() -> None:
    note = anchors(datetime(2026, 9, 24, tzinfo=UTC))
    assert "2025 is over" in note
    assert "2025/26 has finished" in note
    assert "2026/27" in note


def test_in_spring_the_split_season_is_still_being_played() -> None:
    note = anchors(datetime(2026, 3, 10, tzinfo=UTC))
    assert "2025/26 is in its second half" in note
    assert "2024/25 has finished" in note


def test_a_century_boundary_is_written_the_way_seasons_are() -> None:
    assert "2099/00" in anchors(datetime(2099, 9, 1, tzinfo=UTC))


async def test_a_disputed_fact_is_checked_before_it_is_conceded() -> None:
    [message] = await ClockContributor().contribute(ctx(now_in("UTC", clock=lambda: SEPT_24)))
    said = message.content.lower()
    assert "says you are wrong" in said
    assert "before checking" in said
