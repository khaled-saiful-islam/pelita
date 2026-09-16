"""Chat endpoints.

The SSE event names here are the contract the frontend reads. Adding an event
type is additive — a client that does not know it ignores it — which is what
lets later features (sources, usage, suggestions) arrive without a breaking
change.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Request, status
from sse_starlette.sse import EventSourceResponse

from app.api.deps import ChatServiceDep, CurrentUser
from app.api.schemas.chat import SendMessageRequest
from app.core.errors import PelitaError
from app.services.chat_service import DeltaEvent, DoneEvent, ErrorEvent, StartEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def _to_sse(event: object) -> dict[str, str] | None:
    """Translate a service event into an SSE frame."""
    match event:
        case StartEvent():
            return {
                "event": "start",
                "data": json.dumps(
                    {
                        "conversation_id": str(event.conversation_id),
                        "user_message_id": str(event.user_message_id),
                        "assistant_message_id": str(event.assistant_message_id),
                        "title": event.title,
                    }
                ),
            }
        case DeltaEvent():
            return {"event": "token", "data": json.dumps({"text": event.text})}
        case ErrorEvent():
            return {"event": "error", "data": json.dumps({"message": event.message})}
        case DoneEvent():
            return {
                "event": "done",
                "data": json.dumps({"finish_reason": str(event.finish_reason)}),
            }
        case _:  # pragma: no cover - every event type is handled above
            return None


@router.post("/stream")
async def stream(
    payload: SendMessageRequest,
    chat: ChatServiceDep,
    user: CurrentUser,
    request: Request,
) -> EventSourceResponse:
    async def publish() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in chat.stream_turn(
                user_id=user.id,
                conversation_id=payload.conversation_id,
                content=payload.content,
            ):
                # A browser that navigated away should not keep the model running.
                if await request.is_disconnected():
                    logger.info("client disconnected; ending stream")
                    break
                frame = _to_sse(event)
                if frame is not None:
                    yield frame
        except PelitaError as exc:
            # The response has already begun, so an HTTP status is no longer
            # available. The error arrives as an event instead.
            yield {"event": "error", "data": json.dumps({"message": exc.message})}
            yield {"event": "done", "data": json.dumps({"finish_reason": "error"})}

    return EventSourceResponse(publish(), ping=15)


@router.post("/messages/{message_id}/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop(message_id: UUID, chat: ChatServiceDep, user: CurrentUser) -> None:
    """Cancel an in-flight response.

    Returns 204 whether or not anything was still running: by the time a stop
    arrives the stream may already have finished, and that is not an error the
    user needs to see.
    """
    await chat.stop(user_id=user.id, message_id=message_id)
