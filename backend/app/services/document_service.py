"""Attaching files to a conversation.

Validation happens here as well as in the browser. The client check spares
someone a long upload that was always going to be refused; this one is what
actually enforces the limits, because a client check is a courtesy and not a
control.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.tokens import count_tokens
from app.db.models.document import Document
from app.db.repositories.conversations import SqlConversationRepository
from app.services.document_extract import (
    SUPPORTED_DESCRIPTION,
    UnreadableDocument,
    UnsupportedDocument,
    extract,
)

logger = logging.getLogger(__name__)

MAX_FILENAME_LENGTH = 255


def human_size(size_bytes: int) -> str:
    """"5 MB", not "5242880 bytes" — the limit is stated in MB, so the error is."""
    mb = size_bytes / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.1f} MB".replace(".0 ", " ")
    return f"{max(1, round(size_bytes / 1024))} KB"


class DocumentService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        max_bytes: int,
        max_per_conversation: int,
        model: str = "gpt-4o-mini",
    ) -> None:
        self._session = session
        self._max_bytes = max_bytes
        self._max_files = max_per_conversation
        self._model = model

    async def assert_access(self, user_id: UUID, conversation_id: UUID) -> None:
        """Raise unless this user owns the conversation.

        Public because listing needs it too, and a route reaching for a private
        method is a sign the service is missing one.
        """
        await self._assert_owns(user_id, conversation_id)

    async def list_for(self, conversation_id: UUID) -> list[Document]:
        result = await self._session.execute(
            select(Document)
            .where(Document.conversation_id == conversation_id)
            .order_by(Document.created_at)
        )
        return list(result.scalars().all())

    async def attach_to_message(self, conversation_id: UUID, message_id: UUID) -> int:
        """Bind files uploaded since the last message to the one being sent.

        A file is uploaded before there is a message to hang it on, so it sits
        unbound until the user actually sends something. That gap is the whole
        state model: unbound means "still in the composer", bound means "shown
        in the transcript at the point it was added".

        Returns how many were bound, so a caller can log it.
        """
        result = await self._session.execute(
            update(Document)
            .where(Document.conversation_id == conversation_id, Document.message_id.is_(None))
            .values(message_id=message_id)
        )
        return int(result.rowcount or 0)

    async def add(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        filename: str,
        media_type: str,
        data: bytes,
    ) -> Document:
        await self._assert_owns(user_id, conversation_id)

        filename = (filename or "file").strip()[:MAX_FILENAME_LENGTH]
        if not data:
            raise ValidationError(f"{filename} is empty.")
        if len(data) > self._max_bytes:
            raise ValidationError(
                f"{filename} is {human_size(len(data))}. "
                f"The limit is {human_size(self._max_bytes)} per file."
            )

        existing = await self._count(conversation_id)
        if existing >= self._max_files:
            raise ValidationError(
                f"This chat already has {existing} files, which is the limit. "
                "Remove one before adding another."
            )

        try:
            extracted = extract(data, filename=filename, media_type=media_type)
        except UnsupportedDocument as exc:
            raise ValidationError(str(exc)) from exc
        except UnreadableDocument as exc:
            raise ValidationError(str(exc)) from exc

        if not extracted.text.strip():
            raise ValidationError(
                f"No readable text found in {filename}. Upload {SUPPORTED_DESCRIPTION}."
            )

        document = Document(
            conversation_id=conversation_id,
            filename=filename,
            media_type=media_type or "application/octet-stream",
            size_bytes=len(data),
            text=extracted.text,
            unit=extracted.unit,
            unit_count=extracted.count,
            token_count=count_tokens(extracted.text, self._model),
        )
        self._session.add(document)
        await self._session.flush()
        logger.info(
            "attached %s (%s, %d tokens) to conversation %s",
            filename,
            human_size(len(data)),
            document.token_count,
            conversation_id,
        )
        return document

    async def delete(self, *, user_id: UUID, conversation_id: UUID, document_id: UUID) -> None:
        await self._assert_owns(user_id, conversation_id)
        document = await self._session.get(Document, document_id)
        # A stranger's document and a missing one give the same answer.
        if document is None or document.conversation_id != conversation_id:
            raise NotFoundError("No such file.")
        await self._session.delete(document)

    async def _count(self, conversation_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.conversation_id == conversation_id)
        )
        return int(result.scalar_one())

    async def _assert_owns(self, user_id: UUID, conversation_id: UUID) -> None:
        if await SqlConversationRepository(self._session).get(conversation_id, user_id) is None:
            raise NotFoundError("No such conversation.")
