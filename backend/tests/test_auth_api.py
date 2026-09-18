from __future__ import annotations

import httpx
import pytest

from app.api.deps import get_auth_service, get_session, limit_auth
from app.core.config import INSECURE_JWT_SECRET, Settings, deployment_warnings
from app.core.security import hash_password
from app.main import create_app
from app.services.auth_service import AuthService
from tests.fakes import FakeUserRepository, make_user


@pytest.fixture
def repo() -> FakeUserRepository:
    return FakeUserRepository(
        [
            make_user(
                username="admin",
                email="admin@test.com",
                password_hash=hash_password("hunter2hunter2"),
                is_admin=True,
            )
        ]
    )


@pytest.fixture
def client(repo: FakeUserRepository) -> httpx.AsyncClient:
    """The app with its database swapped for an in-memory repository.

    HTTP behaviour — cookies, status codes, the error envelope — is what these
    tests are about; persistence has its own.
    """
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: AuthService(repo)
    app.dependency_overrides[get_session] = _no_session
    # Counting needs a real database, and these tests do not have one by
    # design. The limit has its own tests, including against this same endpoint.
    app.dependency_overrides[limit_auth] = _no_limit
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _no_session():
    yield None


async def _no_limit() -> None:
    return None


async def test_signin_sets_an_httponly_cookie_and_returns_the_user(client) -> None:
    async with client as c:
        response = await c.post(
            "/api/auth/signin", json={"identifier": "admin", "password": "hunter2hunter2"}
        )

    assert response.status_code == 200
    assert response.json()["username"] == "admin"

    cookie = response.headers["set-cookie"]
    assert "pelita_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


async def test_the_token_never_appears_in_the_response_body(client) -> None:
    """It lives in an httpOnly cookie so a successful XSS cannot read it."""
    async with client as c:
        body = (
            await c.post(
                "/api/auth/signin", json={"identifier": "admin", "password": "hunter2hunter2"}
            )
        ).json()

    assert "access_token" not in body
    assert "token" not in body
    assert "password_hash" not in body


async def test_me_requires_a_session(client) -> None:
    async with client as c:
        response = await c.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_cookie_from_signin_authenticates_subsequent_requests(client) -> None:
    async with client as c:
        await c.post(
            "/api/auth/signin", json={"identifier": "admin", "password": "hunter2hunter2"}
        )
        response = await c.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["username"] == "admin"


async def test_bearer_header_works_for_api_clients(client, repo) -> None:
    """Scripts have no cookie jar, and no XSS surface either."""
    from app.core.security import create_access_token

    user = await repo.get_by_username("admin")
    token = create_access_token(user.id)

    async with client as c:
        response = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


async def test_signout_clears_the_cookie(client) -> None:
    async with client as c:
        await c.post(
            "/api/auth/signin", json={"identifier": "admin", "password": "hunter2hunter2"}
        )
        response = await c.post("/api/auth/signout")

    assert response.status_code == 204
    assert 'pelita_session=""' in response.headers["set-cookie"]


async def test_signup_creates_an_account_and_signs_it_in(client, repo) -> None:
    async with client as c:
        response = await c.post(
            "/api/auth/signup",
            json={
                "username": "newbie",
                "email": "newbie@example.com",
                "password": "hunter2hunter2",
            },
        )

    assert response.status_code == 201
    assert response.json()["is_admin"] is False
    assert "pelita_session=" in response.headers["set-cookie"]
    assert repo.count == 2


async def test_duplicate_signup_is_a_conflict_not_a_crash(client) -> None:
    async with client as c:
        response = await c.post(
            "/api/auth/signup",
            json={"username": "admin", "email": "other@example.com", "password": "hunter2hunter2"},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_profile_update_requires_authentication(client) -> None:
    async with client as c:
        response = await c.patch("/api/auth/me", json={"display_name": "Nobody"})
    assert response.status_code == 401


async def test_profile_update_changes_the_display_name(client) -> None:
    async with client as c:
        await c.post(
            "/api/auth/signin", json={"identifier": "admin", "password": "hunter2hunter2"}
        )
        response = await c.patch("/api/auth/me", json={"display_name": "Boss"})

    assert response.status_code == 200
    assert response.json()["display_name"] == "Boss"


async def test_password_change_reissues_the_session(client) -> None:
    """Otherwise changing your password silently signs you out."""
    async with client as c:
        await c.post(
            "/api/auth/signin", json={"identifier": "admin", "password": "hunter2hunter2"}
        )
        response = await c.post(
            "/api/auth/me/password",
            json={"current_password": "hunter2hunter2", "new_password": "brandnewpassword"},
        )

    assert response.status_code == 204
    assert "pelita_session=" in response.headers["set-cookie"]


# --- deployment safety --------------------------------------------------


def test_shipped_defaults_are_flagged_as_unsafe_for_production() -> None:
    # Values are passed explicitly rather than relying on defaults: under Docker
    # the real .env is in the environment, so a default-reading test would pass
    # or fail depending on where it ran.
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        jwt_secret=INSECURE_JWT_SECRET,
        seed_admin_password="admin",
        auth_cookie_secure=False,
    )
    problems = deployment_warnings(settings)
    assert any("JWT_SECRET" in p for p in problems)
    assert any("SEED_ADMIN_PASSWORD" in p for p in problems)
    assert any("AUTH_COOKIE_SECURE" in p for p in problems)


def test_a_short_custom_secret_is_still_flagged() -> None:
    settings = Settings(_env_file=None, jwt_secret="short")  # type: ignore[call-arg]
    assert any("shorter than" in p for p in deployment_warnings(settings))


def test_a_properly_configured_deployment_has_no_warnings() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        jwt_secret="b" * 64,
        seed_admin_password="a-real-password",
        auth_cookie_secure=True,
    )
    assert deployment_warnings(settings) == []
