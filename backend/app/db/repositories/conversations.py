"""Conversation and message data access."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.conversation import Conversation, Message


class ConversationRepository(Protocol):
    async def create(self, user_id: UUID, title: str) -> Conversation: ...
    async def get(self, conversation_id: UUID, user_id: UUID) -> Conversation | None: ...
    async def list_for_user(
        self, user_id: UUID, *, limit: int, offset: int
    ) -> list[Conversation]: ...
    async def count_for_user(self, user_id: UUID) -> int: ...
    async def delete(self, conversation: Conversation) -> None: ...
    async def add_message(self, message: Message) -> Message: ...
    async def get_message(self, message_id: UUID) -> Message | None: ...
    async def recent_messages(self, conversation_id: UUID, *, limit: int) -> list[Message]: ...
    async def touch(self, conversation: Conversation) -> None: ...
    async def recent_user_messages(self, user_id: UUID, *, limit: int) -> list[str]: ...


class SqlConversationRepository(ConversationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: UUID, title: str) -> Conversation:
        conversation = Conversation(user_id=user_id, title=title)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get(self, conversation_id: UUID, user_id: UUID) -> Conversation | None:
        """Ownership is part of the lookup.

        Taking user_id here rather than checking it in the caller means there is
        no path that forgets to check — a missing conversation and someone
        else's conversation are the same answer.
        """
        result = await self._session.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .options(selectinload(Conversation.messages))
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: UUID, *, limit: int, offset: int
    ) -> list[Conversation]:
        result = await self._session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.archived.is_(False))
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_for_user(self, user_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.user_id == user_id, Conversation.archived.is_(False))
        )
        return int(result.scalar_one())

    async def delete(self, conversation: Conversation) -> None:
        await self._session.delete(conversation)

    async def add_message(self, message: Message) -> Message:
        self._session.add(message)
        await self._session.flush()
        return message

    async def get_message(self, message_id: UUID) -> Message | None:
        return await self._session.get(Message, message_id)

    async def recent_messages(self, conversation_id: UUID, *, limit: int) -> list[Message]:
        """Newest `limit` messages, returned oldest-first for prompt assembly."""
        result = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def touch(self, conversation: Conversation) -> None:
        """Bump updated_at so the sidebar reorders."""
        conversation.updated_at = func.now()
        await self._session.flush()

    async def recent_user_messages(self, user_id: UUID, *, limit: int) -> list[str]:
        """This user's latest questions, newest first, across conversations.

        What someone has been asking about is a better signal of what they want
        to read than a standing profile fact — it moves with them.
        """
        result = await self._session.execute(
            select(Message.content)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user_id, Message.role == "user")
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return [content for content in result.scalars().all() if content.strip()]
