"""FastAPI dependencies.

This is the seam between HTTP and logic. Everything below it takes plain
arguments and knows nothing about requests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AuthError
from app.core.security import decode_access_token
from app.db.models.user import User
from app.db.repositories.users import SqlUserRepository
from app.db.session import SessionFactory
from app.services.auth_service import AuthService


async def get_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request: commit on success, roll back on failure."""
    session = SessionFactory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_auth_service(session: SessionDep) -> AuthService:
    return AuthService(SqlUserRepository(session))


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def _token_from(cookie: str | None, authorization: str | None) -> str:
    """Cookie first, bearer header second.

    The browser uses an httpOnly cookie so a successful XSS cannot read the
    token. The header is there for curl, scripts and API clients, which have no
    cookie jar and no XSS surface.
    """
    if cookie:
        return cookie
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    raise AuthError("Not signed in.")


async def current_user(
    auth: AuthServiceDep,
    pelita_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    user_id = decode_access_token(_token_from(pelita_session, authorization))
    return await auth.get_user(user_id)


CurrentUser = Annotated[User, Depends(current_user)]
