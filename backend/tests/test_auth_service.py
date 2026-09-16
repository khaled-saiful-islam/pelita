from __future__ import annotations

import pytest

from app.core.errors import AuthError, ConflictError, NotFoundError, ValidationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.auth_service import AuthService, normalise_email, normalise_username
from tests.fakes import FakeUserRepository, make_user


@pytest.fixture
def repo() -> FakeUserRepository:
    return FakeUserRepository()


@pytest.fixture
def service(repo: FakeUserRepository) -> AuthService:
    return AuthService(repo)


# --- password hashing ---------------------------------------------------


def test_hash_is_salted_so_equal_passwords_differ() -> None:
    assert hash_password("correct horse") != hash_password("correct horse")


def test_verify_accepts_the_right_password_and_rejects_others() -> None:
    stored = hash_password("correct horse")
    assert verify_password("correct horse", stored)
    assert not verify_password("Correct horse", stored)


def test_verify_returns_false_for_a_corrupt_stored_hash() -> None:
    """A bad row in the database is a failed login, not a 500."""
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_password_longer_than_bcrypt_can_see_is_rejected() -> None:
    """bcrypt truncates at 72 bytes silently. Refusing is the honest option."""
    with pytest.raises(ValueError, match="72 bytes"):
        hash_password("a" * 73)


# --- tokens -------------------------------------------------------------


def test_token_round_trips_the_user_id() -> None:
    user = make_user()
    assert decode_access_token(create_access_token(user.id)) == user.id


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c"])
def test_malformed_tokens_are_rejected_with_a_safe_message(token: str) -> None:
    with pytest.raises(AuthError, match="Invalid session"):
        decode_access_token(token)


def test_expired_token_says_so_specifically() -> None:
    user = make_user()
    expired = create_access_token(user.id, expires_minutes=-1)
    with pytest.raises(AuthError, match="expired"):
        decode_access_token(expired)


# --- normalisation ------------------------------------------------------


def test_usernames_are_lowercased() -> None:
    assert normalise_username("  AdMiN  ") == "admin"


@pytest.mark.parametrize("bad", ["a", "-starts-with-dash", "has space", "has@at", "x" * 65])
def test_invalid_usernames_are_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        normalise_username(bad)


@pytest.mark.parametrize("bad", ["nope", "no@domain", "@example.com", "a b@c.com"])
def test_invalid_emails_are_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        normalise_email(bad)


# --- sign up ------------------------------------------------------------


async def test_sign_up_creates_a_non_admin_user_with_a_token(service, repo) -> None:
    result = await service.sign_up(
        username="Aisyah", email="Aisyah@Example.com", password="hunter2hunter2"
    )
    assert result.user.username == "aisyah"
    assert result.user.email == "aisyah@example.com"
    assert result.user.is_admin is False
    assert decode_access_token(result.access_token) == result.user.id
    assert repo.count == 1


async def test_sign_up_never_stores_the_plain_password(service) -> None:
    result = await service.sign_up(
        username="zara", email="zara@example.com", password="hunter2hunter2"
    )
    assert "hunter2hunter2" not in result.user.password_hash
    assert verify_password("hunter2hunter2", result.user.password_hash)


@pytest.mark.parametrize(
    ("field", "value"),
    [("username", "taken"), ("email", "taken@example.com")],
)
async def test_sign_up_rejects_duplicates(service, repo, field, value) -> None:
    repo._users.clear()  # noqa: SLF001
    await repo.add(make_user(username="taken", email="taken@example.com"))

    kwargs = {"username": "fresh", "email": "fresh@example.com", "password": "hunter2hunter2"}
    kwargs[field] = value
    with pytest.raises(ConflictError):
        await service.sign_up(**kwargs)


async def test_sign_up_rejects_a_short_password(service) -> None:
    with pytest.raises(ValidationError, match="at least 8"):
        await service.sign_up(username="bob", email="bob@example.com", password="short")


# --- sign in ------------------------------------------------------------


@pytest.fixture
async def registered(service, repo):
    await service.sign_up(username="ravi", email="ravi@example.com", password="hunter2hunter2")
    return repo


@pytest.mark.parametrize("identifier", ["ravi", "RAVI", "ravi@example.com", "  ravi  "])
async def test_sign_in_accepts_username_or_email_in_any_case(service, registered, identifier):
    result = await service.sign_in(identifier=identifier, password="hunter2hunter2")
    assert result.user.username == "ravi"


@pytest.mark.parametrize(
    ("identifier", "password"),
    [("ravi", "wrong-password"), ("ghost", "hunter2hunter2"), ("ghost@example.com", "x")],
)
async def test_failed_sign_in_is_indistinguishable(service, registered, identifier, password):
    """Different messages for 'no such user' and 'wrong password' turn the
    login form into an account enumeration oracle."""
    with pytest.raises(AuthError) as err:
        await service.sign_in(identifier=identifier, password=password)
    assert str(err.value) == "Incorrect username or password."


async def test_disabled_account_cannot_sign_in(service, repo) -> None:
    await repo.add(
        make_user(
            username="gone",
            email="gone@example.com",
            password_hash=hash_password("hunter2hunter2"),
            is_active=False,
        )
    )
    with pytest.raises(AuthError, match="disabled"):
        await service.sign_in(identifier="gone", password="hunter2hunter2")


async def test_get_user_rejects_a_deactivated_session(service, repo) -> None:
    user = await repo.add(make_user(username="ex", email="ex@example.com", is_active=False))
    with pytest.raises(AuthError, match="no longer valid"):
        await service.get_user(user.id)


# --- profile ------------------------------------------------------------


async def test_update_profile_changes_display_name_and_email(service, registered) -> None:
    user = await registered.get_by_username("ravi")
    updated = await service.update_profile(
        user.id, display_name="  Ravi K  ", email="RaviK@Example.com"
    )
    assert updated.display_name == "Ravi K"
    assert updated.email == "ravik@example.com"


async def test_update_profile_rejects_an_email_another_user_holds(service, registered) -> None:
    await registered.add(make_user(username="other", email="other@example.com"))
    user = await registered.get_by_username("ravi")
    with pytest.raises(ConflictError):
        await service.update_profile(user.id, email="other@example.com")


async def test_keeping_your_own_email_is_not_a_conflict(service, registered) -> None:
    user = await registered.get_by_username("ravi")
    updated = await service.update_profile(user.id, email="ravi@example.com")
    assert updated.email == "ravi@example.com"


async def test_update_profile_rejects_a_blank_display_name(service, registered) -> None:
    user = await registered.get_by_username("ravi")
    with pytest.raises(ValidationError):
        await service.update_profile(user.id, display_name="   ")


async def test_update_profile_on_a_missing_user_is_not_found(service) -> None:
    from uuid import uuid4

    with pytest.raises(NotFoundError):
        await service.update_profile(uuid4(), display_name="x")


# --- password change ----------------------------------------------------


async def test_change_password_requires_the_current_one(service, registered) -> None:
    user = await registered.get_by_username("ravi")
    with pytest.raises(AuthError, match="Current password"):
        await service.change_password(
            user.id, current_password="nope", new_password="newpassword123"
        )


async def test_change_password_replaces_the_hash(service, registered) -> None:
    user = await registered.get_by_username("ravi")
    await service.change_password(
        user.id, current_password="hunter2hunter2", new_password="newpassword123"
    )
    assert verify_password("newpassword123", user.password_hash)
    assert not verify_password("hunter2hunter2", user.password_hash)


async def test_change_password_enforces_the_minimum_length(service, registered) -> None:
    user = await registered.get_by_username("ravi")
    with pytest.raises(ValidationError):
        await service.change_password(
            user.id, current_password="hunter2hunter2", new_password="short"
        )
