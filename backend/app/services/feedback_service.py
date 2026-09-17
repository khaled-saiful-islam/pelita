"""Thumbs up / down on assistant messages.

The value is not the count — it is the reasons attached to the downvotes, which
is the only cheap source of "this was wrong and here is why" a template can
offer out of the box.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.db.models.conversation import Conversation, Message
from app.db.models.feedback import MessageFeedback
from app.providers.base import Role

logger = logging.getLogger(__name__)

RATINGS = frozenset({"up", "down"})
MAX_REASON_LENGTH = 2000


class FeedbackService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rate(
        self, *, user_id: UUID, message_id: UUID, rating: str, reason: str | None = None
    ) -> MessageFeedback:
        if rating not in RATINGS:
            raise ValidationError("Rating must be 'up' or 'down'.")
        if reason is not None:
            reason = reason.strip() or None
            if reason and len(reason) > MAX_REASON_LENGTH:
                raise ValidationError(f"Reason must be under {MAX_REASON_LENGTH} characters.")

        await self._assert_owns_assistant_message(user_id, message_id)

        existing = await self._find(user_id, message_id)
        if existing is not None:
            # Rating again replaces the previous answer rather than appending,
            # so the table says what someone thinks now, not what they clicked.
            existing.rating = rating
            existing.reason = reason
            await self._session.flush()
            return existing

        feedback = MessageFeedback(
            message_id=message_id, user_id=user_id, rating=rating, reason=reason
        )
        self._session.add(feedback)
        await self._session.flush()
        logger.info("feedback %s recorded for message %s", rating, message_id)
        return feedback

    async def clear(self, *, user_id: UUID, message_id: UUID) -> None:
        existing = await self._find(user_id, message_id)
        if existing is not None:
            await self._session.delete(existing)

    async def for_conversation(
        self, *, user_id: UUID, conversation_id: UUID
    ) -> dict[UUID, MessageFeedback]:
        result = await self._session.execute(
            select(MessageFeedback)
            .join(Message, Message.id == MessageFeedback.message_id)
            .where(
                Message.conversation_id == conversation_id,
                MessageFeedback.user_id == user_id,
            )
        )
        return {f.message_id: f for f in result.scalars().all()}

    # -- internals -------------------------------------------------------

    async def _find(self, user_id: UUID, message_id: UUID) -> MessageFeedback | None:
        result = await self._session.execute(
            select(MessageFeedback).where(
                MessageFeedback.message_id == message_id,
                MessageFeedback.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _assert_owns_assistant_message(self, user_id: UUID, message_id: UUID) -> None:
        result = await self._session.execute(
            select(Message.role)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.id == message_id, Conversation.user_id == user_id)
        )
        role = result.scalar_one_or_none()
        if role is None:
            raise NotFoundError("No such message.")
        if role != Role.ASSISTANT:
            raise ValidationError("Only assistant messages can be rated.")
