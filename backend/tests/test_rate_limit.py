"""Rate limiting: the counter, and the address it counts against."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.api.deps import client_address
from app.core.config import Settings
from app.core.errors import RateLimitError
from app.db.models.rate_limit import RateLimitHit
from app.services.rate_limit import Limit, RateLimiter, _floor


class FakeRequest:
    """Only the two things `client_address` reads."""

    def __init__(self, headers: dict[str, str] | None = None, peer: str | None = "10.0.0.1"):
        self.headers = headers or {}
        self.client = type("Client", (), {"host": peer})() if peer else None


# --- windows ------------------------------------------------------------


def test_a_window_is_derived_from_the_clock() -> None:
    """So every worker agrees where one begins without coordinating."""
    moment = datetime(2026, 9, 18, 10, 30, 45, tzinfo=UTC)
    assert _floor(moment, 60) == datetime(2026, 9, 18, 10, 30, 0, tzinfo=UTC)


def test_windows_of_other_sizes_line_up_too() -> None:
    moment = datetime(2026, 9, 18, 10, 37, 0, tzinfo=UTC)
    assert _floor(moment, 300) == datetime(2026, 9, 18, 10, 35, 0, tzinfo=UTC)


# --- counting -----------------------------------------------------------


async def test_requests_under_the_limit_pass(session) -> None:
    limiter = RateLimiter(session)
    for _ in range(3):
        await limiter.check("chat", "user-1", Limit(3))


async def test_one_over_the_limit_is_refused(session) -> None:
    limiter = RateLimiter(session)
    for _ in range(2):
        await limiter.check("chat", "user-1", Limit(2))

    with pytest.raises(RateLimitError) as refused:
        await limiter.check("chat", "user-1", Limit(2))
    assert "Too many requests" in refused.value.message


async def test_the_refusal_says_how_long_to_wait(session) -> None:
    """A 429 without it leaves a client guessing, and guessing means retrying
    immediately."""
    limiter = RateLimiter(session)
    await limiter.check("chat", "user-1", Limit(1))
    with pytest.raises(RateLimitError) as refused:
        await limiter.check("chat", "user-1", Limit(1))

    assert 1 <= refused.value.retry_after <= 60
    assert refused.value.status_code == 429
    assert refused.value.code == "rate_limited"


async def test_identities_are_counted_separately(session) -> None:
    limiter = RateLimiter(session)
    await limiter.check("chat", "user-1", Limit(1))
    # A different user is not affected by the first one's usage.
    await limiter.check("chat", "user-2", Limit(1))


async def test_buckets_are_counted_separately(session) -> None:
    """Uploading a file should not use up someone's chat allowance."""
    limiter = RateLimiter(session)
    await limiter.check("chat", "user-1", Limit(1))
    await limiter.check("upload", "user-1", Limit(1))


async def test_an_earlier_window_does_not_count_against_this_one(session) -> None:
    limiter = RateLimiter(session)
    session.add(
        RateLimitHit(
            bucket="chat",
            identity="user-1",
            window_start=datetime.now(UTC) - timedelta(minutes=5),
            count=99,
        )
    )
    await session.flush()

    await limiter.check("chat", "user-1", Limit(1))


async def test_the_count_is_stored_so_another_worker_sees_it(session) -> None:
    """The whole reason this is in Postgres: an in-process counter is the limit
    times the worker count."""
    await RateLimiter(session).check("chat", "user-1", Limit(5))
    await RateLimiter(session).check("chat", "user-1", Limit(5))

    stored = (
        await session.execute(
            select(RateLimitHit.count).where(RateLimitHit.identity == "user-1")
        )
    ).scalars().all()
    assert stored == [2]


# --- switches -----------------------------------------------------------


async def test_disabled_counts_nothing(session) -> None:
    limiter = RateLimiter(session, enabled=False)
    for _ in range(50):
        await limiter.check("chat", "user-1", Limit(1))
    # Scoped to this test's identity: the table is shared with whatever else
    # has run against this database.
    found = await session.execute(
        select(RateLimitHit).where(RateLimitHit.identity == "user-1")
    )
    assert found.first() is None


async def test_a_zero_limit_is_unlimited(session) -> None:
    """So one bucket can be switched off without disabling the rest."""
    limiter = RateLimiter(session)
    for _ in range(20):
        await limiter.check("chat", "user-1", Limit(0))


async def test_an_empty_identity_is_not_counted(session) -> None:
    """Otherwise every unidentifiable caller shares one bucket and the first
    few lock out the rest."""
    await RateLimiter(session).check("chat", "", Limit(1))
    await RateLimiter(session).check("chat", "", Limit(1))


# --- who is being counted ----------------------------------------------


def test_behind_a_proxy_the_last_hop_is_the_real_one() -> None:
    """nginx appends the peer to whatever the client sent, so the last entry is
    the one it added. Reading the first would let anyone reset their own limit
    by sending a header."""
    request = FakeRequest({"x-forwarded-for": "1.2.3.4, 203.0.113.9"})
    assert client_address(request, Settings(trust_proxy_headers=True)) == "203.0.113.9"


def test_a_spoofed_header_is_ignored_without_a_proxy() -> None:
    request = FakeRequest({"x-forwarded-for": "1.2.3.4"}, peer="10.0.0.1")
    assert client_address(request, Settings(trust_proxy_headers=False)) == "10.0.0.1"


def test_no_header_falls_back_to_the_peer() -> None:
    request = FakeRequest({}, peer="10.0.0.1")
    assert client_address(request, Settings(trust_proxy_headers=True)) == "10.0.0.1"


def test_an_unknown_peer_has_a_name_rather_than_being_empty() -> None:
    """An empty identity is not counted at all, so it must not be the default."""
    assert client_address(FakeRequest({}, peer=None), Settings()) == "unknown"


def test_a_long_header_cannot_overflow_the_column() -> None:
    request = FakeRequest({"x-forwarded-for": "a" * 500})
    assert len(client_address(request, Settings(trust_proxy_headers=True))) <= 128


# --- through the API ----------------------------------------------------


@pytest.fixture
def api(session):
    """The real app, sharing the test's rolled-back session."""
    from app.api.deps import get_session
    from app.main import create_app

    app = create_app()

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_failed_sign_ins_are_counted_even_though_they_roll_back(api, db_user) -> None:
    """The bug this exists to prevent: a failed sign-in raises, the request
    session rolls back, and the attempt un-counts itself — leaving the one
    endpoint most worth limiting as the one with no limit at all.

    Found by hammering the running app, not by a unit test.
    """
    attempt = {"identifier": "tester", "password": "wrong-on-purpose"}
    codes = []
    async with api as client:
        for _ in range(12):
            response = await client.post("/api/auth/signin", json=attempt)
            codes.append(response.status_code)

    assert codes.count(401) == 10, codes
    assert codes[-1] == 429


async def test_the_refusal_carries_retry_after(api, db_user) -> None:
    attempt = {"identifier": "tester", "password": "wrong-on-purpose"}
    async with api as client:
        for _ in range(11):
            response = await client.post("/api/auth/signin", json=attempt)

    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 60
    assert response.json()["error"]["code"] == "rate_limited"
