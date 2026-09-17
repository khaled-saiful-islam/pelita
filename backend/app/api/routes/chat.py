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

from fastapi import APIRouter, status
from sse_starlette.sse import EventSourceResponse

from app.api.deps import ChatServiceDep, CurrentUser, SessionDep
from app.api.schemas.chat import FeedbackRequest, FeedbackResponse, SendMessageRequest
from app.core.errors import PelitaError
from app.services.events import (
    AccountingEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    GuardEventPayload,
    ImagesEvent,
    SourcesEvent,
    StartEvent,
    SuggestionsEvent,
    ToolEvent,
)
from app.services.feedback_service import FeedbackService

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
                        "language": event.language,
                    }
                ),
            }
        case DeltaEvent():
            return {"event": "token", "data": json.dumps({"text": event.text})}
        case GuardEventPayload():
            return {
                "event": "guard",
                "data": json.dumps(
                    {
                        "source": event.source,
                        "severity": event.severity,
                        "rules": list(event.rules),
                        "evidence": event.evidence,
                    }
                ),
            }
        case ToolEvent():
            return {
                "event": "tool",
                "data": json.dumps(
                    {
                        "tool": event.tool,
                        "status": event.status,
                        "label": event.label,
                        "detail": event.detail,
                    }
                ),
            }
        case ImagesEvent():
            return {
                "event": "images",
                "data": json.dumps(
                    {
                        "images": [
                            {
                                "rank": i.rank,
                                "title": i.title,
                                "url": i.url,
                                "source": i.snippet,
                                "thumbnail_url": i.thumbnail_url,
                                "image_url": i.image_url,
                            }
                            for i in event.images
                        ]
                    }
                ),
            }
        case SourcesEvent():
            return {
                "event": "sources",
                "data": json.dumps(
                    {
                        "sources": [
                            {
                                "rank": s.rank,
                                "title": s.title,
                                "url": s.url,
                                "snippet": s.snippet,
                            }
                            for s in event.sources
                        ]
                    }
                ),
            }
        case AccountingEvent():
            return {"event": "usage", "data": json.dumps(event.accounting.as_event())}
        case SuggestionsEvent():
            return {"event": "suggestions", "data": json.dumps({"items": list(event.items)})}
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
) -> EventSourceResponse:
    """Stream a turn.

    Disconnect handling is left entirely to `EventSourceResponse`, which listens
    on the ASGI receive channel and cancels this generator when the client goes
    away. Calling `request.is_disconnected()` in here as well puts two readers on
    the same channel: whichever consumes `http.disconnect` first wins, the
    response never finishes its chunked encoding, and the browser reports
    ERR_INCOMPLETE_CHUNKED_ENCODING after rendering a complete answer. curl does
    not mind, which is what makes it easy to ship.
    """

    async def publish() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in chat.stream_turn(
                user_id=user.id,
                conversation_id=payload.conversation_id,
                content=payload.content,
                regenerate_of=payload.regenerate_of,
                search_mode=payload.search_mode,
            ):
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


@router.put("/messages/{message_id}/feedback", response_model=FeedbackResponse)
async def rate(
    message_id: UUID,
    payload: FeedbackRequest,
    session: SessionDep,
    user: CurrentUser,
) -> FeedbackResponse:
    feedback = await FeedbackService(session).rate(
        user_id=user.id,
        message_id=message_id,
        rating=payload.rating,
        reason=payload.reason,
    )
    return FeedbackResponse.model_validate(feedback)


@router.delete("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def unrate(message_id: UUID, session: SessionDep, user: CurrentUser) -> None:
    await FeedbackService(session).clear(user_id=user.id, message_id=message_id)
