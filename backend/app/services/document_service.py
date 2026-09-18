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
    ExtractedText,
    UnreadableDocument,
    UnsupportedDocument,
    classify,
    extract,
    supported_description,
)
from app.services.image_prep import UnreadableImage, prepare, thumbnail
from app.vision.base import ImageReader, VisionError

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
        reader: ImageReader | None = None,
        image_max_pixels: int = 2_500_000,
        image_jpeg_quality: int = 82,
    ) -> None:
        self._session = session
        self._max_bytes = max_bytes
        self._max_files = max_per_conversation
        self._model = model
        # None means no vision model is configured, which is what makes an
        # image an unsupported file type rather than a broken one.
        self._reader = reader
        self._image_max_pixels = image_max_pixels
        self._image_jpeg_quality = image_jpeg_quality

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
            kind = classify(
                filename=filename, media_type=media_type, images=self._reader is not None
            )
            if kind == "image":
                extracted, preview = await self._read_image(data, filename)
            else:
                extracted, preview = extract(data, filename=filename, media_type=media_type), None
        except UnsupportedDocument as exc:
            raise ValidationError(str(exc)) from exc
        except UnreadableDocument as exc:
            raise ValidationError(str(exc)) from exc

        if not extracted.text.strip():
            raise ValidationError(
                f"No readable text found in {filename}. "
                f"Upload {supported_description(images=self._reader is not None)}."
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
            thumbnail=preview,
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

    async def _read_image(self, data: bytes, filename: str) -> tuple[ExtractedText, str | None]:
        """Transcribe an image, and build the thumbnail for its card.

        Read once, here, rather than on every turn: the text is what the rest of
        the pipeline already understands, so an image that has been read costs
        no more than a text file. The trade is that the transcript is fixed at
        upload — which is why the prompt transcribes everything rather than
        answering a question that has not been asked yet.
        """
        if self._reader is None:  # pragma: no cover - classify() already refused
            raise UnsupportedDocument(f"{filename} is an image, and images are not enabled.")

        try:
            pixels, media_type = prepare(
                data,
                max_pixels=self._image_max_pixels,
                jpeg_quality=self._image_jpeg_quality,
            )
        except UnreadableImage as exc:
            raise UnreadableDocument(str(exc)) from exc

        try:
            text = await self._reader.read(pixels, media_type=media_type)
        except VisionError as exc:
            # The reason is the user's — a rate limit and a bad key need
            # different actions, and "could not read it" says neither.
            raise UnreadableDocument(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - an unexpected shape is still a refusal
            logger.exception("vision call failed for %s", filename)
            raise UnreadableDocument(f"{filename} could not be read.") from exc

        if not text.strip():
            raise UnreadableDocument(
                f"Nothing readable was found in {filename}."
            )

        # A thumbnail is built from the original bytes, not the downscaled ones:
        # the vision copy is sized for a model, and cropping quality for the
        # model would show in the card.
        return ExtractedText(text=text, unit="image", count=1), thumbnail(data)

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
