"""Sharing a conversation.

Two audiences, deliberately in one file so the difference between them is
impossible to miss while reading:

- `/conversations/{id}/share` — the owner. Authenticated, ownership enforced by
  the lookup.
- `/shares/{token}` — anybody at all. No auth, no cookies, rate limited, and
  never indexed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep, limit_share
from app.api.schemas.share import PublicConversationResponse, ShareResponse
from app.core.errors import NotFoundError
from app.db.models.share import ConversationShare
from app.services.share_service import ShareService

owner_router = APIRouter(prefix="/conversations/{conversation_id}/share", tags=["shares"])
public_router = APIRouter(prefix="/shares", tags=["shares"])


def _response(share: ConversationShare, request: Request, settings) -> ShareResponse:
    return ShareResponse(
        token=share.token,
        url=_public_url(share.token, request, settings),
        title=share.title,
        message_count=share.message_count,
        view_count=share.view_count,
        last_viewed_at=share.last_viewed_at,
        created_at=share.created_at,
    )


def _public_url(token: str, request: Request, settings) -> str:
    """The link someone will paste into a message.

    `PUBLIC_BASE_URL` when set, because behind a proxy the request's own host is
    whatever the proxy chose to forward and a link built from it can point
    somewhere nobody else can reach. Falling back to the request keeps a local
    clone working with no configuration.
    """
    base = (settings.public_base_url or str(request.base_url)).rstrip("/")
    return f"{base}/s/{token}"


@owner_router.get("", response_model=ShareResponse)
async def show(
    conversation_id: UUID,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> ShareResponse:
    share = await ShareService(session).get(user_id=user.id, conversation_id=conversation_id)
    if share is None:
        raise NotFoundError("This conversation is not shared.")
    return _response(share, request, settings)


@owner_router.post("", response_model=ShareResponse, status_code=status.HTTP_201_CREATED)
async def create(
    conversation_id: UUID,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> ShareResponse:
    """Share it, or refresh an existing link with everything said since."""
    share = await ShareService(session).share(
        user_id=user.id, conversation_id=conversation_id
    )
    return _response(share, request, settings)


@owner_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def revoke(
    conversation_id: UUID, session: SessionDep, user: CurrentUser
) -> None:
    await ShareService(session).revoke(user_id=user.id, conversation_id=conversation_id)


@public_router.get(
    "/{token}",
    response_model=PublicConversationResponse,
    dependencies=[Depends(limit_share)],
)
async def public_view(
    token: str, response: Response, session: SessionDep
) -> PublicConversationResponse:
    """The only unauthenticated route that returns anyone's content.

    A revoked link and a token that never existed give the same answer, so the
    endpoint cannot be used to learn which tokens are real.
    """
    # Someone sharing a chat means "this person I sent it to", not "the web".
    # Search engines honour this; it costs nothing and is the difference between
    # a private link and a published page.
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    # Nothing here is personalised, but it is somebody's conversation — a shared
    # cache holding it is not a risk worth taking for a page this cheap.
    response.headers["Cache-Control"] = "no-store"

    public = await ShareService(session).view(token)
    return PublicConversationResponse(
        title=public.title,
        messages=public.messages,
        shared_at=public.shared_at,
        message_count=public.message_count,
    )
