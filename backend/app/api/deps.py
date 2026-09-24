"""FastAPI dependencies.

This is the seam between HTTP and logic. Everything below it takes plain
arguments and knows nothing about requests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.registry import build_contributors
from app.core.config import Settings, get_settings
from app.core.errors import AuthError, ForbiddenError
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
from app.services.chat_service import ChatService, TurnSettings
from app.services.quota import TokenQuota
from app.services.rate_limit import Limit, RateLimiter
from app.tools.registry import build_tools


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


async def current_admin(user: CurrentUser) -> User:
    """A dependency rather than a check inside each handler.

    A check you have to remember is a check someone forgets on the one route
    that matters.
    """
    if not user.is_admin:
        raise ForbiddenError("This needs an administrator account.")
    return user


AdminUser = Annotated[User, Depends(current_admin)]


def get_chat_service(settings: SettingsDep) -> ChatService:
    """Built per request, but cheap: the provider holds no connection pool,
    contributors are stateless, and tools are thin wrappers."""
    return ChatService(
        session_maker=session_scope,
        provider=build_provider(settings),
        contributor_factory=lambda memories: build_contributors(settings, memories=memories),
        cancellation=cancellation_registry,
        tools=build_tools(settings),
        guards=build_guards(settings),
        settings=TurnSettings(
            budget=TokenBudget(
                memory=settings.memory_token_budget,
                tools=settings.tools_token_budget,
                history=settings.history_token_budget,
            ),
            pricing=Pricing.from_settings(settings),
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            supported_languages=tuple(settings.supported_language_list),
            default_language=settings.default_language,
            suggestions_enabled=settings.suggestions_enabled,
            suggestions_count=settings.suggestions_count,
            memory_auto_extract=settings.memory_auto_extract,
            memory_max_per_user=settings.memory_max_per_user,
            document_max_bytes=settings.document_max_bytes,
            document_max_per_conversation=settings.document_max_per_conversation,
            tool_calling_enabled=settings.tool_calling_enabled,
            tool_max_iterations=settings.tool_max_iterations,
            default_timezone=settings.default_timezone,
        ),
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


# --- rate limiting ------------------------------------------------------


def client_address(request: Request, settings: Settings) -> str:
    """The caller's address, as well as it can be known.

    nginx sets `X-Forwarded-For $proxy_add_x_forwarded_for`, which *appends* the
    real peer to whatever the client sent. So the last entry is the one the
    proxy added and the only one worth believing — reading the first would let
    anyone reset their own limit by sending a header.

    With `trust_proxy_headers=false` the header is ignored entirely, which is
    the right posture when the API is exposed without a proxy in front.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1][:128]
    return (request.client.host if request.client else "unknown")[:128]


async def limit_chat(session: SessionDep, settings: SettingsDep, user: CurrentUser) -> None:
    """The expensive one: every request here can become several model calls.

    Two different controls, in order of cost to evaluate: how often this account
    may ask, then how much it may spend. Both run before the turn, so a refusal
    costs a query rather than a model call.
    """
    await RateLimiter(session, enabled=settings.rate_limit_enabled).check(
        "chat", str(user.id), Limit(settings.rate_limit_chat_per_minute)
    )
    await TokenQuota(session).check(user.id, user.daily_token_limit)


async def limit_upload(session: SessionDep, settings: SettingsDep, user: CurrentUser) -> None:
    await RateLimiter(session, enabled=settings.rate_limit_enabled).check(
        "upload", str(user.id), Limit(settings.rate_limit_upload_per_minute)
    )


async def limit_share(request: Request, session: SessionDep, settings: SettingsDep) -> None:
    """Per address, because nobody is signed in — this is the open endpoint.

    Its own bucket rather than sharing `auth`: a popular shared link should not
    be able to lock its readers out of signing in.
    """
    await RateLimiter(session, enabled=settings.rate_limit_enabled).check(
        "share", client_address(request, settings), Limit(settings.rate_limit_share_per_minute)
    )


async def limit_auth(request: Request, session: SessionDep, settings: SettingsDep) -> None:
    """Per address, because these are the endpoints reached before anyone is
    signed in — and the ones worth guessing passwords at."""
    await RateLimiter(session, enabled=settings.rate_limit_enabled).check(
        "auth", client_address(request, settings), Limit(settings.rate_limit_auth_per_minute)
    )
