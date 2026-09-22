"""Reading and writing artifacts.

Ownership is a parameter of every lookup rather than a check the caller has to
remember. `get(artifact_id, user_id)` returning None for someone else's
artifact is indistinguishable from it not existing, which is what we want a
stranger to learn.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact import Artifact, ArtifactVersion


class SqlArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        message_id: UUID | None,
        kind: str,
        title: str,
        html: str,
        design_spec: dict[str, Any],
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        build_ms: int = 0,
    ) -> Artifact:
        """The artifact and its first version, in one transaction."""
        artifact = Artifact(
            conversation_id=conversation_id,
            user_id=user_id,
            message_id=message_id,
            kind=kind,
            title=title,
            current_version=1,
        )
        artifact.versions.append(
            ArtifactVersion(
                version=1,
                html=html,
                design_spec=design_spec,
                size_bytes=len(html.encode()),
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                build_ms=build_ms,
            )
        )
        self._session.add(artifact)
        await self._session.flush()
        return artifact

    async def add_version(
        self,
        artifact: Artifact,
        *,
        html: str,
        design_spec: dict[str, Any],
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        build_ms: int = 0,
    ) -> ArtifactVersion:
        """Write the next version. Never over the last one — the version
        selector needs something to select, and an edit that erases what it
        replaced cannot be undone."""
        version = ArtifactVersion(
            version=artifact.current_version + 1,
            html=html,
            design_spec=design_spec,
            size_bytes=len(html.encode()),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            build_ms=build_ms,
        )
        # Appended through the relationship, not inserted by foreign key: the
        # collection is already loaded, and a row written behind its back
        # leaves `artifact.versions` missing the version just written.
        artifact.versions.append(version)
        artifact.current_version = version.version
        await self._session.flush()
        return version

    async def get(self, artifact_id: UUID, user_id: UUID) -> Artifact | None:
        return (
            await self._session.execute(
                select(Artifact).where(
                    Artifact.id == artifact_id, Artifact.user_id == user_id
                )
            )
        ).scalars().first()

    async def version(
        self, artifact: Artifact, number: int | None = None
    ) -> ArtifactVersion | None:
        """One version, or the current one when no number is given."""
        wanted = artifact.current_version if number is None else number
        return next((v for v in artifact.versions if v.version == wanted), None)

    async def for_conversation(self, conversation_id: UUID, user_id: UUID) -> list[Artifact]:
        result = await self._session.execute(
            select(Artifact)
            .where(
                Artifact.conversation_id == conversation_id,
                Artifact.user_id == user_id,
            )
            .order_by(Artifact.created_at)
        )
        return list(result.scalars().all())

    async def count_for_conversation(self, conversation_id: UUID) -> int:
        """How many exist already, for the per-conversation ceiling. Counted
        rather than tracked, so deleting one frees its slot."""
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(Artifact)
                .where(Artifact.conversation_id == conversation_id)
            )
            or 0
        )

    async def bind_to_message(self, artifact: Artifact, message_id: UUID) -> None:
        artifact.message_id = message_id
        await self._session.flush()
