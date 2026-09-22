"""Public links to an artifact.

The same two decisions as `share_service`, for the same reasons, and they are
worth restating rather than cross-referencing because this is the other place
in the app where a mistake is public:

1. **A frozen copy, not a pointer.** A link that followed the artifact would
   republish every later edit without the owner deciding to. A copy written
   before those edits existed cannot leak them however wrong a query is.
2. **What a stranger sees is four columns**, named here. Everything else about
   the artifact — who made it, what it cost, which model, what the design
   direction was, every other version — is absent by construction rather than
   filtered out.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.models.artifact_share import ArtifactShare
from app.db.repositories.artifacts import SqlArtifactRepository

logger = logging.getLogger(__name__)

# 256 bits. The URL is the credential, so guessing must not be a strategy.
TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class PublicArtifact:
    """What a stranger with the link is given. Nothing else exists to them."""

    title: str
    kind: str
    html: str
    width: int
    height: int


class ArtifactShareService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def share(
        self, *, user_id: UUID, artifact_id: UUID, version: int | None = None
    ) -> ArtifactShare:
        """Create the link, or refresh an existing one with a new copy.

        Refreshing keeps the token, so a link already sent keeps working and
        picks up the version the owner is looking at now. Anyone who wants the
        old link dead revokes it, which is a different intent with its own
        button.
        """
        repo = SqlArtifactRepository(self._session)
        artifact = await repo.get(artifact_id, user_id)
        if artifact is None:
            raise NotFoundError("No such artifact.")
        chosen = await repo.version(artifact, version)
        if chosen is None:
            raise NotFoundError("No such version.")

        spec = chosen.design_spec or {}
        existing = await self._for_artifact(artifact_id)
        if existing is not None:
            existing.title = artifact.title
            existing.html = chosen.html
            existing.version = chosen.version
            existing.width = int(spec.get("width") or 0)
            existing.height = int(spec.get("height") or 0)
            await self._session.flush()
            logger.info("refreshed share for artifact %s", artifact_id)
            return existing

        share = ArtifactShare(
            artifact_id=artifact_id,
            user_id=user_id,
            token=secrets.token_urlsafe(TOKEN_BYTES),
            title=artifact.title,
            kind=artifact.kind,
            html=chosen.html,
            version=chosen.version,
            width=int(spec.get("width") or 0),
            height=int(spec.get("height") or 0),
        )
        self._session.add(share)
        await self._session.flush()
        logger.info("shared artifact %s", artifact_id)
        return share

    async def get(self, *, user_id: UUID, artifact_id: UUID) -> ArtifactShare | None:
        if await SqlArtifactRepository(self._session).get(artifact_id, user_id) is None:
            raise NotFoundError("No such artifact.")
        return await self._for_artifact(artifact_id)

    async def revoke(self, *, user_id: UUID, artifact_id: UUID) -> None:
        """Idempotent: revoking something already revoked is the outcome the
        caller wanted, and an error there only invites a retry loop."""
        if await SqlArtifactRepository(self._session).get(artifact_id, user_id) is None:
            raise NotFoundError("No such artifact.")
        share = await self._for_artifact(artifact_id)
        if share is None:
            return
        await self._session.delete(share)
        logger.info("revoked share for artifact %s", artifact_id)

    async def view(self, token: str) -> PublicArtifact:
        """Resolve a token. A revoked link and one that never existed are the
        same answer, so a token cannot be used to learn which ones are real."""
        share = (
            await self._session.execute(
                select(ArtifactShare).where(ArtifactShare.token == token)
            )
        ).scalars().first()
        if share is None:
            raise NotFoundError("This link is not available. It may have been revoked.")

        await self._count_view(share.id)
        return PublicArtifact(
            title=share.title,
            kind=share.kind,
            html=share.html,
            width=share.width,
            height=share.height,
        )

    async def _count_view(self, share_id: UUID) -> None:
        """A view that cannot be counted is still a view."""
        try:
            await self._session.execute(
                update(ArtifactShare)
                .where(ArtifactShare.id == share_id)
                .values(view_count=ArtifactShare.__table__.c.view_count + 1)
            )
        except Exception:  # noqa: BLE001 - a counter is never worth a 500
            logger.exception("could not record a view of artifact share %s", share_id)

    async def _for_artifact(self, artifact_id: UUID) -> ArtifactShare | None:
        return (
            await self._session.execute(
                select(ArtifactShare).where(ArtifactShare.artifact_id == artifact_id)
            )
        ).scalars().first()
