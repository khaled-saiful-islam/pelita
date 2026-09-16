"""Signup, login and profile updates.

No FastAPI import appears here, which is enforced by `tests/test_layering.py`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from uuid import UUID

from app.core.errors import AuthError, ConflictError, NotFoundError, ValidationError
from app.core.security import (
    MAX_PASSWORD_BYTES,
    MIN_PASSWORD_LENGTH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.models.user import User
from app.db.repositories.users import UserRepository

logger = logging.getLogger(__name__)

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True, slots=True)
class AuthResult:
    user: User
    access_token: str


def normalise_username(raw: str) -> str:
    username = raw.strip().lower()
    if not USERNAME_PATTERN.match(username):
        raise ValidationError(
            "Username must be 2-64 characters, starting with a letter or digit, "
            "and may contain only letters, digits, dots, hyphens and underscores."
        )
    return username


def normalise_email(raw: str) -> str:
    email = raw.strip().lower()
    if not EMAIL_PATTERN.match(email) or len(email) > 320:
        raise ValidationError("That does not look like an email address.")
    return email


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValidationError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def sign_up(self, *, username: str, email: str, password: str) -> AuthResult:
        username = normalise_username(username)
        email = normalise_email(email)
        validate_password(password)

        if await self._users.get_by_username(username):
            raise ConflictError("That username is taken.")
        if await self._users.get_by_email(email):
            raise ConflictError("That email is already registered.")

        user = await self._users.add(
            User(
                username=username,
                email=email,
                password_hash=hash_password(password),
                display_name=username,
                is_admin=False,
                is_active=True,
            )
        )
        logger.info("user signed up: %s", username)
        return AuthResult(user=user, access_token=create_access_token(user.id))

    async def sign_in(self, *, identifier: str, password: str) -> AuthResult:
        """Accepts a username or an email.

        Every failure returns the same message. Distinguishing "no such user"
        from "wrong password" turns the login form into an account enumeration
        oracle.
        """
        lookup = identifier.strip().lower()
        user = await self._users.get_by_username(lookup)
        if user is None and "@" in lookup:
            user = await self._users.get_by_email(lookup)

        if user is None or not verify_password(password, user.password_hash):
            raise AuthError("Incorrect username or password.")
        if not user.is_active:
            raise AuthError("This account has been disabled.")

        return AuthResult(user=user, access_token=create_access_token(user.id))

    async def get_user(self, user_id: UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthError("Your session is no longer valid.")
        return user

    async def update_profile(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        email: str | None = None,
    ) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")

        if display_name is not None:
            cleaned = display_name.strip()
            if not 1 <= len(cleaned) <= 120:
                raise ValidationError("Display name must be 1-120 characters.")
            user.display_name = cleaned

        if email is not None:
            normalised = normalise_email(email)
            if normalised != user.email:
                existing = await self._users.get_by_email(normalised)
                if existing is not None and existing.id != user.id:
                    raise ConflictError("That email is already registered.")
                user.email = normalised

        return await self._users.save(user)

    async def change_password(
        self, user_id: UUID, *, current_password: str, new_password: str
    ) -> None:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        if not verify_password(current_password, user.password_hash):
            raise AuthError("Current password is incorrect.")

        validate_password(new_password)
        user.password_hash = hash_password(new_password)
        await self._users.save(user)
        logger.info("password changed for %s", user.username)
