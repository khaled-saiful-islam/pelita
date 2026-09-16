"""In-memory doubles.

Service tests run against these rather than Postgres, so they are fast and say
something about the logic instead of about SQLAlchemy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.db.models.user import User
from app.db.repositories.users import UserRepository


class FakeUserRepository(UserRepository):
    def __init__(self, users: list[User] | None = None) -> None:
        self._users: dict[UUID, User] = {u.id: u for u in (users or [])}

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_username(self, username: str) -> User | None:
        target = username.strip().lower()
        return next((u for u in self._users.values() if u.username == target), None)

    async def get_by_email(self, email: str) -> User | None:
        target = email.strip().lower()
        return next((u for u in self._users.values() if u.email == target), None)

    async def add(self, user: User) -> User:
        # The database assigns these; in memory we have to.
        if user.id is None:
            user.id = uuid4()
        now = datetime.now(UTC)
        user.created_at = user.created_at or now
        user.updated_at = now
        self._users[user.id] = user
        return user

    async def save(self, user: User) -> User:
        user.updated_at = datetime.now(UTC)
        self._users[user.id] = user
        return user

    @property
    def count(self) -> int:
        return len(self._users)


def make_user(
    *,
    username: str = "someone",
    email: str = "someone@example.com",
    password_hash: str = "x",  # noqa: S107
    is_admin: bool = False,
    is_active: bool = True,
) -> User:
    user = User(
        username=username,
        email=email,
        password_hash=password_hash,
        display_name=username,
        is_admin=is_admin,
        is_active=is_active,
    )
    user.id = uuid4()
    user.created_at = datetime.now(UTC)
    user.updated_at = user.created_at
    return user
