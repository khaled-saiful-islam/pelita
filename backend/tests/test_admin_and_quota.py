"""Admin user management and the 24-hour token quota."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError, RateLimitError, ValidationError
from app.core.security import hash_password, verify_password
from app.db.models.conversation import Conversation, Message
from app.db.models.user import User
from app.services.admin_service import AdminService
from app.services.quota import TokenQuota


@pytest.fixture
async def sole_admin(session, admin) -> User:
    """`admin` guaranteed to be the only active administrator.

    The database this runs against has the seeded `admin` account in it, which
    is a real active administrator — so a test about "the last one" has to say
    so rather than assume it.
    """
    others = (
        await session.execute(
            select(User).where(User.is_admin.is_(True), User.id != admin.id)
        )
    ).scalars().all()
    for user in others:
        user.is_active = False
    await session.flush()
    return admin


@pytest.fixture
async def admin(session) -> User:
    user = User(
        username="boss",
        email="boss@example.com",
        password_hash=hash_password("hunter2hunter2"),
        is_admin=True,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def spend(session, user: User, *, prompt: int, completion: int, age_hours: float = 0):
    """Record a turn's usage, optionally backdated out of the window."""
    conversation = Conversation(user_id=user.id, title="Spent")
    session.add(conversation)
    await session.flush()
    message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="x",
        prompt_tokens=prompt,
        completion_tokens=completion,
    )
    session.add(message)
    await session.flush()
    if age_hours:
        message.created_at = datetime.now(UTC) - timedelta(hours=age_hours)
        await session.flush()
    return message


# --- the quota ----------------------------------------------------------


async def test_no_limit_means_unlimited(session, db_user) -> None:
    """The default. A template that throttles by surprise is worse than one
    that does not throttle."""
    await spend(session, db_user, prompt=10_000, completion=10_000)
    usage = await TokenQuota(session).check(db_user.id, None)
    assert usage.unlimited


async def test_usage_sums_both_directions(session, db_user) -> None:
    await spend(session, db_user, prompt=300, completion=200)
    usage = await TokenQuota(session).usage(db_user.id, 1000)
    assert usage.tokens == 500
    assert usage.remaining == 500


async def test_spending_over_the_limit_is_refused(session, db_user) -> None:
    await spend(session, db_user, prompt=600, completion=500)
    with pytest.raises(RateLimitError, match="allowance"):
        await TokenQuota(session).check(db_user.id, 1000)


async def test_exactly_at_the_limit_is_refused(session, db_user) -> None:
    """"1,000 used of 1,000" is spent, not nearly spent."""
    await spend(session, db_user, prompt=500, completion=500)
    with pytest.raises(RateLimitError):
        await TokenQuota(session).check(db_user.id, 1000)


async def test_older_usage_falls_out_of_the_window(session, db_user) -> None:
    """Rolling, so there is no midnight where a blocked account unblocks and
    the whole allowance goes in an hour."""
    await spend(session, db_user, prompt=900, completion=0, age_hours=25)
    usage = await TokenQuota(session).check(db_user.id, 1000)
    assert usage.tokens == 0


async def test_usage_just_inside_the_window_still_counts(session, db_user) -> None:
    await spend(session, db_user, prompt=900, completion=0, age_hours=23)
    assert (await TokenQuota(session).usage(db_user.id, 1000)).tokens == 900


async def test_one_users_spending_does_not_count_against_another(session, db_user) -> None:
    other = User(
        username="other",
        email="other@example.com",
        password_hash=hash_password("hunter2hunter2"),
    )
    session.add(other)
    await session.flush()
    await spend(session, other, prompt=5000, completion=0)

    usage = await TokenQuota(session).check(db_user.id, 1000)
    assert usage.tokens == 0


async def test_the_refusal_says_what_was_used_and_allowed(session, db_user) -> None:
    await spend(session, db_user, prompt=1500, completion=0)
    with pytest.raises(RateLimitError) as refused:
        await TokenQuota(session).check(db_user.id, 1000)

    assert "1,000-token" in refused.value.message
    assert "1,500 used" in refused.value.message
    assert refused.value.status_code == 429


# --- creating accounts --------------------------------------------------


async def test_an_admin_can_create_a_user(session, admin) -> None:
    user = await AdminService(session).create(
        username="Newcomer", email="NEW@Example.com", password="hunter2hunter2"
    )
    # Lowercased on the way in, so the unique index means what it looks like.
    assert user.username == "newcomer"
    assert user.email == "new@example.com"
    assert user.is_active and not user.is_admin
    assert user.daily_token_limit is None


async def test_a_created_user_can_actually_sign_in(session, admin) -> None:
    """The password has to be hashed the same way sign-up hashes it, or the
    account exists and is unusable."""
    user = await AdminService(session).create(
        username="newcomer", email="new@example.com", password="hunter2hunter2"
    )
    assert verify_password("hunter2hunter2", user.password_hash)


async def test_a_duplicate_username_is_a_conflict(session, admin, db_user) -> None:
    with pytest.raises(ConflictError, match="username"):
        await AdminService(session).create(
            username=db_user.username, email="fresh@example.com", password="hunter2hunter2"
        )


async def test_a_duplicate_email_is_a_conflict(session, admin, db_user) -> None:
    with pytest.raises(ConflictError, match="email"):
        await AdminService(session).create(
            username="fresh", email=db_user.email, password="hunter2hunter2"
        )


async def test_a_short_password_is_refused(session, admin) -> None:
    with pytest.raises(ValidationError, match="at least 8"):
        await AdminService(session).create(
            username="fresh", email="fresh@example.com", password="short"
        )


async def test_a_negative_limit_is_refused(session, admin) -> None:
    with pytest.raises(ValidationError, match="negative"):
        await AdminService(session).create(
            username="fresh",
            email="fresh@example.com",
            password="hunter2hunter2",
            daily_token_limit=-1,
        )


# --- changing accounts --------------------------------------------------


async def test_an_admin_can_disable_a_user(session, admin, db_user) -> None:
    updated = await AdminService(session).update(
        db_user.id, acting_admin_id=admin.id, is_active=False
    )
    assert updated.is_active is False


async def test_an_admin_can_set_and_clear_a_limit(session, admin, db_user) -> None:
    service = AdminService(session)
    assert (
        await service.update(db_user.id, acting_admin_id=admin.id, daily_token_limit=5000)
    ).daily_token_limit == 5000

    # Explicit, because `daily_token_limit: null` in a PATCH cannot be told
    # apart from "not mentioned".
    assert (
        await service.update(db_user.id, acting_admin_id=admin.id, clear_limit=True)
    ).daily_token_limit is None


async def test_a_limit_of_zero_is_a_real_limit(session, admin, db_user) -> None:
    """Zero stops the account entirely; it is not "unlimited" spelled oddly."""
    updated = await AdminService(session).update(
        db_user.id, acting_admin_id=admin.id, daily_token_limit=0
    )
    assert updated.daily_token_limit == 0
    with pytest.raises(RateLimitError):
        await TokenQuota(session).check(db_user.id, updated.daily_token_limit)


async def test_an_admin_can_reset_a_password(session, admin, db_user) -> None:
    updated = await AdminService(session).update(
        db_user.id, acting_admin_id=admin.id, password="brand-new-password"
    )
    assert verify_password("brand-new-password", updated.password_hash)


async def test_updating_someone_who_does_not_exist_is_not_found(session, admin) -> None:
    with pytest.raises(NotFoundError):
        await AdminService(session).update(uuid4(), acting_admin_id=admin.id, is_active=False)


# --- not locking yourself out -------------------------------------------


async def test_an_admin_cannot_disable_themselves(session, admin) -> None:
    with pytest.raises(ValidationError, match="your own account"):
        await AdminService(session).update(
            admin.id, acting_admin_id=admin.id, is_active=False
        )


async def test_an_admin_cannot_demote_themselves(session, admin) -> None:
    with pytest.raises(ValidationError, match="your own account"):
        await AdminService(session).update(admin.id, acting_admin_id=admin.id, is_admin=False)


async def test_the_last_administrator_cannot_be_disabled(session, sole_admin, db_user) -> None:
    """A single-admin install is the normal case for this template, and an
    admin with no way back in has only a database console left."""
    with pytest.raises(ValidationError, match="last administrator"):
        await AdminService(session).update(
            sole_admin.id, acting_admin_id=db_user.id, is_active=False
        )


async def test_the_last_administrator_cannot_be_demoted(session, sole_admin, db_user) -> None:
    with pytest.raises(ValidationError, match="last administrator"):
        await AdminService(session).update(
            sole_admin.id, acting_admin_id=db_user.id, is_admin=False
        )


async def test_a_second_administrator_makes_the_first_removable(
    session, sole_admin, db_user
) -> None:
    """The rule is about the last one, not about admins in general."""
    second = User(
        username="second",
        email="second@example.com",
        password_hash=hash_password("hunter2hunter2"),
        is_admin=True,
        is_active=True,
    )
    session.add(second)
    await session.flush()

    updated = await AdminService(session).update(
        sole_admin.id, acting_admin_id=second.id, is_admin=False
    )
    assert updated.is_admin is False


async def test_a_disabled_admin_is_no_cover_for_the_last_active_one(
    session, sole_admin, db_user
) -> None:
    """Otherwise the last *active* admin can be removed because a disabled one
    exists on paper, and nobody can sign in."""
    ghost = User(
        username="ghost",
        email="ghost@example.com",
        password_hash=hash_password("hunter2hunter2"),
        is_admin=True,
        is_active=False,
    )
    session.add(ghost)
    await session.flush()

    with pytest.raises(ValidationError, match="last administrator"):
        await AdminService(session).update(
            sole_admin.id, acting_admin_id=db_user.id, is_admin=False
        )


# --- listing ------------------------------------------------------------


async def test_listing_reports_usage_next_to_the_limit(session, admin, db_user) -> None:
    """An admin setting a cap needs to know what the account actually uses."""
    await spend(session, db_user, prompt=120, completion=80)
    db_user.daily_token_limit = 1000
    await session.flush()

    listed = {m.user.username: m for m in await AdminService(session).list_users()}
    assert listed["tester"].usage.tokens == 200
    assert listed["tester"].usage.remaining == 800
    assert listed["boss"].usage.unlimited


# --- through the API ----------------------------------------------------


@pytest.fixture
def api(session):
    from app.api.deps import get_session
    from app.main import create_app

    app = create_app()

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def signed_in(client, username: str, password: str = "hunter2hunter2"):
    response = await client.post(
        "/api/auth/signin", json={"identifier": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response


async def test_a_normal_user_cannot_reach_admin_routes(api, db_user) -> None:
    async with api as client:
        await signed_in(client, "tester")
        response = await client.get("/api/admin/users")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_an_anonymous_request_is_unauthorised_not_forbidden(api) -> None:
    async with api as client:
        response = await client.get("/api/admin/users")
    assert response.status_code == 401


async def test_an_admin_creates_a_user_over_the_api(api, admin) -> None:
    async with api as client:
        await signed_in(client, "boss")
        response = await client.post(
            "/api/admin/users",
            json={
                "username": "recruit",
                "email": "recruit@example.com",
                "password": "hunter2hunter2",
                "daily_token_limit": 5000,
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "recruit"
    assert body["daily_token_limit"] == 5000
    assert body["tokens_used_24h"] == 0


async def test_disabling_a_user_over_the_api(api, admin, db_user, session) -> None:
    async with api as client:
        await signed_in(client, "boss")
        response = await client.patch(
            f"/api/admin/users/{db_user.id}", json={"is_active": False}
        )

    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_a_disabled_user_cannot_sign_in(api, admin, db_user) -> None:
    async with api as client:
        await signed_in(client, "boss")
        await client.patch(f"/api/admin/users/{db_user.id}", json={"is_active": False})
        client.cookies.clear()

        response = await client.post(
            "/api/auth/signin",
            json={"identifier": "tester", "password": "hunter2hunter2"},
        )

    assert response.status_code == 401
    assert "disabled" in response.json()["error"]["message"]


async def test_a_user_can_see_their_own_allowance(api, db_user, session) -> None:
    await spend(session, db_user, prompt=100, completion=50)
    db_user.daily_token_limit = 1000
    await session.flush()

    async with api as client:
        await signed_in(client, "tester")
        response = await client.get("/api/auth/me/usage")

    assert response.status_code == 200
    assert response.json() == {
        "tokens_used_24h": 150,
        "daily_token_limit": 1000,
        "remaining": 850,
    }


async def test_a_user_over_their_limit_cannot_start_a_turn(api, db_user, session) -> None:
    """Refused before the turn, so it costs a query rather than a model call."""
    await spend(session, db_user, prompt=2000, completion=0)
    db_user.daily_token_limit = 1000
    await session.flush()

    async with api as client:
        await signed_in(client, "tester")
        response = await client.post(
            "/api/chat/stream", json={"conversation_id": None, "content": "hello"}
        )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


async def test_the_seeded_admin_is_still_an_admin(session) -> None:
    """The account `make up` creates is what an operator signs in as; if it
    lost its flag, nobody could reach this feature at all."""
    seeded = (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalars().first()
    if seeded is not None:  # the seed runs outside the test transaction
        assert seeded.is_admin
