"""Reading artifacts back.

The stream delivers a document once, while it is being made. Everything
afterwards — a reload, a second visit, switching versions — comes through here.

Ownership is a parameter of every lookup, so somebody else's artifact is
indistinguishable from one that never existed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.api.schemas.artifact import (
    ArtifactDetail,
    ArtifactList,
    ArtifactSummary,
    ArtifactVersionSummary,
)
from app.artifacts.registry import build_kinds
from app.core.errors import NotFoundError
from app.db.models.artifact import Artifact, ArtifactVersion
from app.db.repositories.artifacts import SqlArtifactRepository

router = APIRouter(prefix="/artifacts", tags=["artifacts"])
by_conversation = APIRouter(prefix="/conversations/{conversation_id}/artifacts", tags=["artifacts"])


def _size(version: ArtifactVersion) -> tuple[int, int]:
    spec = version.design_spec or {}
    return int(spec.get("width") or 0), int(spec.get("height") or 0)


def _summary(artifact: Artifact, version: ArtifactVersion) -> ArtifactSummary:
    width, height = _size(version)
    return ArtifactSummary(
        id=artifact.id,
        message_id=artifact.message_id,
        kind=artifact.kind,
        title=artifact.title,
        version=version.version,
        width=width,
        height=height,
        created_at=artifact.created_at,
    )


async def _load(
    session, artifact_id: UUID, user_id: UUID, number: int | None = None
) -> tuple[Artifact, ArtifactVersion]:
    repo = SqlArtifactRepository(session)
    artifact = await repo.get(artifact_id, user_id)
    if artifact is None:
        raise NotFoundError("No such artifact.")
    version = await repo.version(artifact, number)
    if version is None:
        raise NotFoundError("No such version.")
    return artifact, version


@router.get("/{artifact_id}", response_model=ArtifactDetail)
async def read(
    artifact_id: UUID,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
    version: int | None = None,
) -> ArtifactDetail:
    artifact, chosen = await _load(session, artifact_id, user.id, version)
    kind = build_kinds(settings).get(artifact.kind)
    return ArtifactDetail(
        **_summary(artifact, chosen).model_dump(),
        html=chosen.html,
        # From the kind, so the frame and the shared page cannot disagree about
        # what this document may do.
        sandbox=kind.sandbox.iframe_sandbox if kind else "",
        versions=[ArtifactVersionSummary.model_validate(v) for v in artifact.versions],
    )


@router.get("/{artifact_id}/raw", response_class=Response)
async def raw(
    artifact_id: UUID,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
    version: int | None = None,
) -> Response:
    """The document on its own, for opening in a tab and for printing.

    Served under the kind's own CSP. `sandbox` in a header does for a whole
    document what the attribute does for a frame: an opaque origin, so the
    poster cannot read a cookie or call the API with one even though it is on
    the same host.
    """
    artifact, chosen = await _load(session, artifact_id, user.id, version)
    kind = build_kinds(settings).get(artifact.kind)
    policy = kind.sandbox.csp if kind else "sandbox; default-src 'none'"
    return Response(
        content=chosen.html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": policy,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "private, no-store",
        },
    )


@by_conversation.get("", response_model=ArtifactList)
async def listing(
    conversation_id: UUID, session: SessionDep, user: CurrentUser
) -> ArtifactList:
    """Everything this conversation made, so a reload can put the cards back."""
    repo = SqlArtifactRepository(session)
    artifacts = await repo.for_conversation(conversation_id, user.id)
    items = []
    for artifact in artifacts:
        current = await repo.version(artifact)
        if current is not None:
            items.append(_summary(artifact, current))
    return ArtifactList(items=items)
