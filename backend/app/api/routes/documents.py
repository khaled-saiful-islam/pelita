"""Files attached to a conversation.

Validation is repeated here rather than trusted from the browser: a client check
saves someone a long upload, but it is a courtesy, not a control.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep, limit_upload
from app.api.schemas.document import DocumentList, DocumentResponse
from app.core.errors import ValidationError
from app.services.document_service import DocumentService, human_size
from app.vision.registry import build_image_reader

router = APIRouter(prefix="/conversations/{conversation_id}/documents", tags=["documents"])


def _service(session, settings) -> DocumentService:
    return DocumentService(
        session,
        max_bytes=settings.document_max_bytes,
        max_per_conversation=settings.document_max_per_conversation,
        model=settings.llm_model,
        # None unless VISION_MODEL is set, which is what decides whether an
        # image is a supported file type at all.
        reader=build_image_reader(settings),
        image_max_pixels=settings.vision_max_pixels,
        image_jpeg_quality=settings.vision_jpeg_quality,
    )


@router.get("", response_model=DocumentList)
async def index(
    conversation_id: UUID, session: SessionDep, user: CurrentUser, settings: SettingsDep
) -> DocumentList:
    service = _service(session, settings)
    await service.assert_access(user.id, conversation_id)
    return DocumentList(
        items=[DocumentResponse.model_validate(d) for d in await service.list_for(conversation_id)],
        max_files=settings.document_max_per_conversation,
        max_bytes=settings.document_max_bytes,
    )


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_upload)],
)
async def upload(
    conversation_id: UUID,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
    file: UploadFile = File(...),
) -> DocumentResponse:
    data = await file.read()
    # Read fully before checking: Starlette has already buffered it, and the
    # size limit that matters is enforced by the reverse proxy in front.
    if len(data) > settings.document_max_bytes:
        raise ValidationError(
            f"{file.filename} is {human_size(len(data))}. "
            f"The limit is {human_size(settings.document_max_bytes)} per file."
        )

    document = await _service(session, settings).add(
        user_id=user.id,
        conversation_id=conversation_id,
        filename=file.filename or "file",
        media_type=file.content_type or "application/octet-stream",
        data=data,
    )
    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def destroy(
    conversation_id: UUID,
    document_id: UUID,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> None:
    await _service(session, settings).delete(
        user_id=user.id, conversation_id=conversation_id, document_id=document_id
    )
