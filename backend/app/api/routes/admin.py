"""Account management, for administrators.

Every route here is behind `AdminUser`, which is a dependency rather than a
check inside each handler — a check you have to remember is a check someone
will forget on the one route that matters.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import AdminUser, SessionDep
from app.api.schemas.admin import (
    AdminUserList,
    AdminUserResponse,
    CreateUserRequest,
    UpdateUserRequest,
)
from app.services.admin_service import AdminService, ManagedUser

router = APIRouter(prefix="/admin/users", tags=["admin"])


def _response(managed: ManagedUser) -> AdminUserResponse:
    return AdminUserResponse(
        id=managed.user.id,
        username=managed.user.username,
        email=managed.user.email,
        display_name=managed.user.display_name,
        is_admin=managed.user.is_admin,
        is_active=managed.user.is_active,
        daily_token_limit=managed.user.daily_token_limit,
        tokens_used_24h=managed.usage.tokens,
        created_at=managed.user.created_at,
    )


@router.get("", response_model=AdminUserList)
async def index(session: SessionDep, admin: AdminUser) -> AdminUserList:
    return AdminUserList(
        items=[_response(managed) for managed in await AdminService(session).list_users()]
    )


@router.post("", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
async def create(
    body: CreateUserRequest, session: SessionDep, admin: AdminUser
) -> AdminUserResponse:
    user = await AdminService(session).create(
        username=body.username,
        email=str(body.email),
        password=body.password,
        display_name=body.display_name,
        is_admin=body.is_admin,
        daily_token_limit=body.daily_token_limit,
    )
    # Freshly created, so nothing has been spent yet.
    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
        daily_token_limit=user.daily_token_limit,
        tokens_used_24h=0,
        created_at=user.created_at,
    )


@router.patch("/{user_id}", response_model=AdminUserResponse)
async def update(
    user_id: UUID, body: UpdateUserRequest, session: SessionDep, admin: AdminUser
) -> AdminUserResponse:
    service = AdminService(session)
    user = await service.update(
        user_id,
        acting_admin_id=admin.id,
        is_active=body.is_active,
        is_admin=body.is_admin,
        display_name=body.display_name,
        password=body.password,
        daily_token_limit=body.daily_token_limit,
        clear_limit=body.clear_limit,
    )
    from app.services.quota import TokenQuota

    usage = await TokenQuota(session).usage(user.id, user.daily_token_limit)
    return _response(ManagedUser(user=user, usage=usage))
