"""Public, read-only links to a conversation.

Everything here exists to answer one question safely: what may a stranger with a
URL see? The answer is an explicit allow-list, frozen at the moment of sharing.

Two decisions carry the security, and both are the boring option on purpose:

1. **A snapshot, not a live view.** A public reader never touches the
   conversation. A filter that hides later messages is one bug away from not
   hiding them; a copy written before those messages existed cannot leak them.
2. **Fields are copied in, never filtered out.** Adding a column to `messages`
   can therefore never publish it by accident. A deny-list gets this backwards
   and fails silently the first time the schema grows.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models.conversation import Conversation, Message
from app.db.models.share import ConversationShare
from app.db.repositories.conversations import SqlConversationRepository

logger = logging.getLogger(__name__)

# 256 bits. The URL is the credential, so guessing must not be a strategy:
# at a million tries a second this outlives the sun.
TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class PublicConversation:
    """What a stranger with the link is given. Nothing else exists to them."""

    title: str
    messages: list[dict[str, Any]]
    shared_at: datetime
    message_count: int


class ShareService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- the owner's side ------------------------------------------------

    async def share(self, *, user_id: UUID, conversation_id: UUID) -> ConversationShare:
        """Create the link, or refresh an existing one with a new snapshot.

        Refreshing keeps the token, so a link already sent to someone keeps
        working and picks up the rest of the conversation. Anyone who wants the
        old link dead revokes it instead — which is a different intent and has
        its own button.
        """
        conversation = await self._owned(user_id, conversation_id)
        snapshot = [_public_message(m) for m in conversation.messages]

        existing = await self._for_conversation(conversation_id)
        if existing is not None:
            existing.title = conversation.title
            existing.snapshot = snapshot
            existing.message_count = len(snapshot)
            await self._session.flush()
            logger.info("refreshed share for conversation %s", conversation_id)
            return existing

        share = ConversationShare(
            conversation_id=conversation_id,
            user_id=user_id,
            token=secrets.token_urlsafe(TOKEN_BYTES),
            title=conversation.title,
            snapshot=snapshot,
            message_count=len(snapshot),
        )
        self._session.add(share)
        await self._session.flush()
        logger.info("shared conversation %s", conversation_id)
        return share

    async def get(self, *, user_id: UUID, conversation_id: UUID) -> ConversationShare | None:
        """The owner's view of their own link, or None if it is not shared."""
        await self._owned(user_id, conversation_id)
        return await self._for_conversation(conversation_id)

    async def revoke(self, *, user_id: UUID, conversation_id: UUID) -> None:
        """Delete the link. The URL stops resolving immediately.

        Idempotent: revoking something already revoked is the outcome the caller
        wanted, and an error there only invites a retry loop.
        """
        await self._owned(user_id, conversation_id)
        share = await self._for_conversation(conversation_id)
        if share is None:
            return
        await self._session.delete(share)
        logger.info("revoked share for conversation %s", conversation_id)

    # -- the public side -------------------------------------------------

    async def view(self, token: str) -> PublicConversation:
        """Resolve a token. Never reveals whether one merely expired or never
        existed — both are simply not found.
        """
        share = (
            await self._session.execute(
                select(ConversationShare).where(ConversationShare.token == token)
            )
        ).scalars().first()
        if share is None:
            raise NotFoundError("This link is not available. It may have been revoked.")

        await self._count_view(share.id)
        return PublicConversation(
            title=share.title,
            messages=list(share.snapshot),
            shared_at=share.created_at,
            message_count=share.message_count,
        )

    async def _count_view(self, share_id: UUID) -> None:
        """Bump the counter without loading or locking the row.

        Wrapped because a view that cannot be counted is still a view: failing
        to increment must never turn a working link into an error page.
        """
        try:
            await self._session.execute(
                update(ConversationShare)
                .where(ConversationShare.id == share_id)
                .values(
                    view_count=ConversationShare.__table__.c.view_count + 1,
                    last_viewed_at=datetime.now(UTC),
                )
            )
        except Exception:  # noqa: BLE001 - a counter is never worth a 500
            logger.exception("could not record a view of share %s", share_id)

    # -- internals -------------------------------------------------------

    async def _owned(self, user_id: UUID, conversation_id: UUID) -> Conversation:
        """Ownership as a parameter of the lookup, not a check afterwards."""
        conversation = await SqlConversationRepository(self._session).get(
            conversation_id, user_id
        )
        if conversation is None:
            raise NotFoundError("No such conversation.")
        return conversation

    async def _for_conversation(self, conversation_id: UUID) -> ConversationShare | None:
        return (
            await self._session.execute(
                select(ConversationShare).where(
                    ConversationShare.conversation_id == conversation_id
                )
            )
        ).scalars().first()


def _public_message(message: Message) -> dict[str, Any]:
    """One message, reduced to what a stranger may see.

    Built by naming what goes in. Everything absent here is absent by
    construction, including things that do not exist yet — which is the point.

    Left out deliberately:

    - **ids** — nothing public should be addressable, and an id invites trying it
      against an authenticated endpoint.
    - **cost, token counts, usage_source, model** — the owner's billing, and a
      running inventory of which model a deployment runs.
    - **finish_reason** — internal state.
    - **feedback and guard findings** — the owner's private opinion of an answer,
      and a map of what trips the injection guard.
    - **attached file contents** — the filename says a file was there; its text
      is the user's document and was never the thing being shared.
    """
    return {
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "sources": [
            {
                "rank": source.rank,
                "title": source.title,
                "url": source.url,
                "snippet": source.snippet,
                "thumbnail_url": source.thumbnail_url or None,
                "image_url": source.image_url or None,
            }
            for source in message.sources
        ],
        "documents": [
            {
                "filename": document.filename,
                "unit": document.unit,
                "unit_count": document.unit_count,
                # The picture the sharer saw on the card. The extracted text —
                # the actual contents of their file — is never included.
                "thumbnail": document.thumbnail,
            }
            for document in message.documents
        ],
    }
