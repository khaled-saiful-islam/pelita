"""Memory management.

Everything Pelita remembers about you is listed, editable and deletable here.
Memory a person cannot see or correct is a liability rather than a feature.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.api.schemas.memory import (
    CreateMemoryRequest,
    MemoryList,
    MemoryResponse,
    UpdateMemoryRequest,
)
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("", response_model=MemoryList)
async def index(session: SessionDep, user: CurrentUser, settings: SettingsDep) -> MemoryList:
    service = MemoryService(session, max_per_user=settings.memory_max_per_user)
    return MemoryList(
        items=[MemoryResponse.model_validate(m) for m in await service.list_for(user.id)],
        limit=settings.memory_max_per_user,
    )


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create(
    payload: CreateMemoryRequest,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> MemoryResponse:
    service = MemoryService(session, max_per_user=settings.memory_max_per_user)
    return MemoryResponse.model_validate(
        await service.add(user.id, payload.content, source="user")
    )


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update(
    memory_id: UUID,
    payload: UpdateMemoryRequest,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> MemoryResponse:
    service = MemoryService(session, max_per_user=settings.memory_max_per_user)
    return MemoryResponse.model_validate(
        await service.update(
            user.id, memory_id, content=payload.content, enabled=payload.enabled
        )
    )


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def destroy(
    memory_id: UUID, session: SessionDep, user: CurrentUser, settings: SettingsDep
) -> None:
    service = MemoryService(session, max_per_user=settings.memory_max_per_user)
    await service.delete(user.id, memory_id)
