"""Conversation listing, reading, renaming and deletion."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import PlainTextResponse

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.api.schemas.chat import (
    ConversationDetail,
    ConversationList,
    ConversationSummary,
    ConversationTotals,
    FeedbackResponse,
    MessageResponse,
    RenameConversationRequest,
)
from app.core.errors import NotFoundError
from app.db.repositories.conversations import SqlConversationRepository
from app.services.accounting_service import Pricing, summarise
from app.services.chat_service import list_conversations
from app.services.export_service import filename_for, to_markdown
from app.services.feedback_service import FeedbackService

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


@router.post("", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED)
async def create(session: SessionDep, user: CurrentUser) -> ConversationSummary:
    """Start an empty conversation.

    Needed because a file is attached to a conversation, and someone can attach
    one before they have typed anything. The title stays "New chat" until the
    first message replaces it.
    """
    conversation = await SqlConversationRepository(session).create(user.id, "New chat")
    return ConversationSummary.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def show(
    conversation_id: UUID,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> ConversationDetail:
    conversation = await SqlConversationRepository(session).get(conversation_id, user.id)
    if conversation is None:
        # Someone else's conversation and a missing one give the same answer, so
        # the endpoint cannot be used to discover which ids exist.
        raise NotFoundError("No such conversation.")

    # Ratings come with the conversation rather than as a second request, so the
    # thumbs render in their correct state on first paint instead of popping in.
    ratings = await FeedbackService(session).for_conversation(
        user_id=user.id, conversation_id=conversation_id
    )
    # Built explicitly rather than validated from the ORM object, because
    # totals and feedback are computed and have nowhere to come from otherwise.
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        language=conversation.language,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageResponse.model_validate(m) for m in conversation.messages],
        feedback={
            message_id: FeedbackResponse.model_validate(f)
            for message_id, f in ratings.items()
        },
        totals=ConversationTotals(
            **summarise(conversation.messages, Pricing.from_settings(settings))
        ),
    )


@router.get("/{conversation_id}/export", response_class=PlainTextResponse)
async def export(
    conversation_id: UUID,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> PlainTextResponse:
    """Download the conversation as Markdown."""
    conversation = await SqlConversationRepository(session).get(conversation_id, user.id)
    if conversation is None:
        raise NotFoundError("No such conversation.")

    return PlainTextResponse(
        content=to_markdown(conversation, app_name=settings.app_name),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_for(conversation)}"'
        },
    )


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
