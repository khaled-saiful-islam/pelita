"""Auth endpoints.

The session token is set as an httpOnly cookie rather than returned in the body,
so a successful XSS cannot read it. The same token is accepted as a bearer
header for scripts and API clients.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import AuthServiceDep, CurrentUser, SessionDep, SettingsDep, limit_auth
from app.api.schemas.admin import UsageResponse
from app.api.schemas.auth import (
    ChangePasswordRequest,
    SignInRequest,
    SignUpRequest,
    UpdateProfileRequest,
    UserResponse,
)
from app.core.config import Settings
from app.core.security import create_access_token
from app.services.quota import TokenQuota

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "pelita_session"


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        # SameSite=lax is not sent on cross-site POSTs, which is what makes CSRF
        # tokens unnecessary here: the SPA and API are same-origin behind nginx.
        samesite="lax",
        secure=settings.auth_cookie_secure,
        path="/",
    )


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_auth)],
)
async def sign_up(
    payload: SignUpRequest,
    auth: AuthServiceDep,
    settings: SettingsDep,
    response: Response,
) -> UserResponse:
    result = await auth.sign_up(
        username=payload.username, email=payload.email, password=payload.password
    )
    _set_session_cookie(response, result.access_token, settings)
    return UserResponse.model_validate(result.user)


@router.post("/signin", response_model=UserResponse, dependencies=[Depends(limit_auth)])
async def sign_in(
    payload: SignInRequest,
    auth: AuthServiceDep,
    settings: SettingsDep,
    response: Response,
) -> UserResponse:
    result = await auth.sign_in(identifier=payload.identifier, password=payload.password)
    _set_session_cookie(response, result.access_token, settings)
    return UserResponse.model_validate(result.user)


@router.post("/signout", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me/usage", response_model=UsageResponse)
async def my_usage(user: CurrentUser, session: SessionDep) -> UsageResponse:
    """What this account has spent and what it may spend.

    Its own endpoint rather than a field on /me, because it costs a query and
    every page load asks who you are.
    """
    usage = await TokenQuota(session).usage(user.id, user.daily_token_limit)
    return UsageResponse(
        tokens_used_24h=usage.tokens,
        daily_token_limit=usage.limit,
        remaining=usage.remaining,
    )


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    payload: UpdateProfileRequest, auth: AuthServiceDep, user: CurrentUser
) -> UserResponse:
    updated = await auth.update_profile(
        user.id, display_name=payload.display_name, email=payload.email
    )
    return UserResponse.model_validate(updated)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_auth)],
)
async def change_password(
    payload: ChangePasswordRequest,
    auth: AuthServiceDep,
    user: CurrentUser,
    settings: SettingsDep,
    response: Response,
) -> None:
    await auth.change_password(
        user.id,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    # Re-issue so the session survives the change rather than silently expiring.
    _set_session_cookie(response, create_access_token(user.id), settings)
