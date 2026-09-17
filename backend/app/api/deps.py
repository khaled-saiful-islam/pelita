"""FastAPI dependencies.

This is the seam between HTTP and logic. Everything below it takes plain
arguments and knows nothing about requests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.registry import build_contributors
from app.core.config import Settings, get_settings
from app.core.errors import AuthError
from app.core.security import decode_access_token
from app.db.models.user import User
from app.db.repositories.users import SqlUserRepository
from app.db.session import SessionFactory, session_scope
from app.guards.registry import build_guards
from app.providers.base import TokenBudget
from app.providers.registry import build_provider
from app.services.accounting_service import Pricing
from app.services.auth_service import AuthService
from app.services.cancellation import registry as cancellation_registry
from app.services.chat_service import ChatService
from app.tools.serpapi import SerpApiSearch


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


def get_chat_service(settings: SettingsDep) -> ChatService:
    """Built per request, but cheap: the provider holds no connection pool and
    contributors are stateless."""
    return ChatService(
        session_maker=session_scope,
        provider=build_provider(settings),
        contributor_factory=lambda memories: build_contributors(settings, memories=memories),
        cancellation=cancellation_registry,
        budget=TokenBudget(
            memory=settings.memory_token_budget,
            tools=settings.tools_token_budget,
            history=settings.history_token_budget,
        ),
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        pricing=Pricing.from_settings(settings),
        supported_languages=settings.supported_language_list,
        default_language=settings.default_language,
        # None when no key is configured, so the toggle simply does nothing
        # rather than failing every search.
        search=(
            SerpApiSearch(
                api_key=settings.serpapi_key, base_url=settings.serpapi_base_url
            )
            if settings.search_enabled
            else None
        ),
        guards=build_guards(settings),
        search_limit=settings.search_max_results,
        image_limit=settings.image_max_results,
        suggestions_enabled=settings.suggestions_enabled,
        suggestions_count=settings.suggestions_count,
        memory_auto_extract=settings.memory_auto_extract,
        memory_max_per_user=settings.memory_max_per_user,
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
