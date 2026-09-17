"""Shared fixtures.

The database fixture wraps each test in a transaction and rolls it back, so
integration tests share one schema without leaking rows into each other or into
the development data. No test needs to remember to clean up.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models.user import User
from app.services.cancellation import CancellationRegistry


@pytest.fixture(scope="session")
def database_url() -> str:
    return get_settings().database_url


@pytest.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    """A session whose work is always rolled back.

    The outer transaction is never committed, so `session.commit()` inside the
    code under test commits only to a nested savepoint and the whole thing
    disappears when the test ends.
    """
    engine = create_async_engine(database_url, poolclass=None)
    connection = await engine.connect()
    transaction = await connection.begin()
    maker = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    db = maker()
    try:
        yield db
    finally:
        await db.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
async def db_user(session: AsyncSession) -> User:
    user = User(
        username="tester",
        email="tester@example.com",
        password_hash=hash_password("hunter2hunter2"),
        display_name="Tester",
        is_admin=False,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
def registry() -> CancellationRegistry:
    """A fresh cancellation registry per test, so one turn cannot cancel another."""
    return CancellationRegistry()
