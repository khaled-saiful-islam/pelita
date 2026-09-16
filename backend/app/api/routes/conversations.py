"""Conversation listing, reading, renaming and deletion."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas.chat import (
    ConversationDetail,
    ConversationList,
    ConversationSummary,
    RenameConversationRequest,
)
from app.core.errors import NotFoundError
from app.db.repositories.conversations import SqlConversationRepository
from app.services.chat_service import list_conversations

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationList)
async def index(
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ConversationList:
    items, total = await list_conversations(session, user.id, limit=limit, offset=offset)
    return ConversationList(
        items=[ConversationSummary.model_validate(c) for c in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def show(conversation_id: UUID, session: SessionDep, user: CurrentUser) -> ConversationDetail:
    conversation = await SqlConversationRepository(session).get(conversation_id, user.id)
    if conversation is None:
        # Someone else's conversation and a missing one give the same answer, so
        # the endpoint cannot be used to discover which ids exist.
        raise NotFoundError("No such conversation.")
    return ConversationDetail.model_validate(conversation)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename(
    conversation_id: UUID,
    payload: RenameConversationRequest,
    session: SessionDep,
    user: CurrentUser,
) -> ConversationSummary:
    repo = SqlConversationRepository(session)
    conversation = await repo.get(conversation_id, user.id)
    if conversation is None:
        raise NotFoundError("No such conversation.")
    conversation.title = payload.title.strip()
    return ConversationSummary.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def destroy(conversation_id: UUID, session: SessionDep, user: CurrentUser) -> None:
    repo = SqlConversationRepository(session)
    conversation = await repo.get(conversation_id, user.id)
    if conversation is None:
        raise NotFoundError("No such conversation.")
    await repo.delete(conversation)
