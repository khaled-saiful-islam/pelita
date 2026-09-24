"""Reading artifacts back.

The stream delivers a document once, while it is being made. Everything
afterwards — a reload, a second visit, switching versions — comes through here.

Ownership is a parameter of every lookup, so somebody else's artifact is
indistinguishable from one that never existed.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep, limit_share
from app.api.schemas.artifact import (
    AppState,
    ArtifactDetail,
    ArtifactList,
    ArtifactShareResponse,
    ArtifactSummary,
    ArtifactVersionSummary,
    EditTextRequest,
    ReviseRequest,
)
from app.artifacts.base import ArtifactUnavailable, DesignSpec, Finished
from app.artifacts.raster import RasterUnavailable, to_pdf, to_png
from app.artifacts.registry import build_kinds
from app.artifacts.text_edit import apply_text, readable_text
from app.core.errors import NotFoundError, ValidationError
from app.db.models.artifact import Artifact, ArtifactVersion
from app.db.models.artifact_share import ArtifactShare
from app.db.repositories.artifacts import SqlArtifactRepository
from app.services.artifact_share_service import ArtifactShareService

router = APIRouter(prefix="/artifacts", tags=["artifacts"])
by_conversation = APIRouter(prefix="/conversations/{conversation_id}/artifacts", tags=["artifacts"])
public_router = APIRouter(prefix="/shares/artifacts", tags=["artifacts"])

# What a shared or downloaded document is served with, alongside the kind's own
# policy. `noindex` because sharing a poster means "this person I sent it to"
# and not "the web"; `no-store` because a public cache holding someone's poster
# outlives their decision to revoke the link.
PUBLIC_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


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


@router.get("/{artifact_id}/text", response_model=list[str])
async def text(
    artifact_id: UUID, session: SessionDep, user: CurrentUser, version: int | None = None
) -> list[str]:
    """The words on it, in the order they appear.

    Here so a caller can check its numbering against the server's before
    sending changes, rather than discovering a mismatch by corrupting a poster.
    """
    _, chosen = await _load(session, artifact_id, user.id, version)
    return readable_text(chosen.html)


@router.post("/{artifact_id}/text", response_model=ArtifactDetail)
async def edit_text(
    artifact_id: UUID,
    payload: EditTextRequest,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> ArtifactDetail:
    """Change the words. No model, no wait, no chance of a different poster.

    Every tag, attribute and byte of CSS is copied through untouched, which is
    what makes this safe to do with nothing checking the result. It is still a
    new version, because an edit that overwrites what it replaced cannot be
    undone.
    """
    artifact, current = await _load(session, artifact_id, user.id)

    edited = apply_text(current.html, {c.index: c.text for c in payload.changes})
    if edited != current.html:
        # Corrected in place rather than versioned. Fixing a typo is not a new
        # draft of the poster, and a version list where every entry differs by
        # one character is a version list nobody reads.
        current.html = edited
        current.size_bytes = len(edited.encode())
        await session.commit()

    return await read(artifact_id, session, user, settings)


@router.post("/{artifact_id}/revise", response_model=ArtifactDetail)
async def revise(
    artifact_id: UUID,
    payload: ReviseRequest,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> ArtifactDetail:
    """Ask for a change to the design itself.

    One composing call, from the direction the poster already has. The
    direction step is skipped because it was settled when the poster was made,
    and the refinement pass is skipped because the person is looking at the
    result and can simply ask again.
    """
    repo = SqlArtifactRepository(session)
    artifact, current = await _load(session, artifact_id, user.id)
    kind = build_kinds(settings).get(artifact.kind)
    if kind is None or not hasattr(kind, "revise"):
        raise ValidationError("This kind of artifact cannot be revised.")

    built = None
    try:
        async for update in kind.revise(
            html=current.html,
            spec=DesignSpec.from_dict(current.design_spec or {}),
            instruction=payload.instruction,
        ):
            if isinstance(update, Finished):
                built = update.built
    except ArtifactUnavailable as exc:
        raise ValidationError(str(exc)) from exc

    if built is None:
        raise ValidationError("The design model returned nothing. The poster is unchanged.")

    await repo.add_version(
        artifact,
        html=built.html,
        design_spec=built.spec.as_dict(),
        model=built.model,
        prompt_tokens=built.prompt_tokens,
        completion_tokens=built.completion_tokens,
        build_ms=built.build_ms,
    )
    await session.commit()
    return await read(artifact_id, session, user, settings)


# The most an app may keep. A task list with a year of history is a few tens of
# kilobytes; past this it is not state, it is a database, and a row this size
# would be read on every open.
MAX_STATE_BYTES = 256 * 1024


async def _owned(session, artifact_id: UUID, user_id: UUID) -> Artifact:
    artifact = await SqlArtifactRepository(session).get(artifact_id, user_id)
    if artifact is None:
        raise NotFoundError("No such artifact.")
    return artifact


@router.get("/{artifact_id}/state", response_model=AppState)
async def read_state(artifact_id: UUID, session: SessionDep, user: CurrentUser) -> AppState:
    """What this person's copy of the app last saved. `null` before the first save."""
    await _owned(session, artifact_id, user.id)
    return AppState(data=await SqlArtifactRepository(session).state(artifact_id, user.id))


@router.put("/{artifact_id}/state", status_code=status.HTTP_204_NO_CONTENT)
async def save_state(
    artifact_id: UUID, payload: AppState, session: SessionDep, user: CurrentUser
) -> None:
    """Keep what the app saved, for this person only.

    Owner-only, like every other artifact route: the app is framed with an
    opaque origin and cannot call this itself, so the panel saves on its
    behalf and only for the artifact it is showing.
    """
    await _owned(session, artifact_id, user.id)
    size = len(json.dumps(payload.data, separators=(",", ":")).encode())
    if size > MAX_STATE_BYTES:
        raise ValidationError(
            f"This app is trying to keep {size // 1024} KB; the limit is "
            f"{MAX_STATE_BYTES // 1024} KB."
        )
    await SqlArtifactRepository(session).save_state(artifact_id, user.id, payload.data)
    await session.commit()


@router.delete("/{artifact_id}/state", status_code=status.HTTP_204_NO_CONTENT)
async def clear_state(artifact_id: UUID, session: SessionDep, user: CurrentUser) -> None:
    """Start the app over, empty."""
    await _owned(session, artifact_id, user.id)
    await SqlArtifactRepository(session).clear_state(artifact_id, user.id)
    await session.commit()


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


# -- the owner's side ----------------------------------------------------


def _share_response(share: ArtifactShare, request: Request, settings) -> ArtifactShareResponse:
    # `PUBLIC_BASE_URL` when set: behind a proxy the request's own host is
    # whatever the proxy forwarded, and a link built from it can point
    # somewhere nobody else can reach.
    base = (settings.public_base_url or str(request.base_url)).rstrip("/")
    return ArtifactShareResponse(
        token=share.token,
        url=f"{base}/a/{share.token}",
        title=share.title,
        version=share.version,
        view_count=share.view_count,
        created_at=share.created_at,
    )


@router.get("/{artifact_id}/share", response_model=ArtifactShareResponse | None)
async def show_share(
    artifact_id: UUID,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
) -> ArtifactShareResponse | None:
    share = await ArtifactShareService(session).get(user_id=user.id, artifact_id=artifact_id)
    return None if share is None else _share_response(share, request, settings)


@router.post("/{artifact_id}/share", response_model=ArtifactShareResponse)
async def create_share(
    artifact_id: UUID,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
    version: int | None = None,
) -> ArtifactShareResponse:
    """Share it, or refresh an existing link with the version being looked at."""
    share = await ArtifactShareService(session).share(
        user_id=user.id, artifact_id=artifact_id, version=version
    )
    await session.commit()
    return _share_response(share, request, settings)


@router.delete("/{artifact_id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(artifact_id: UUID, session: SessionDep, user: CurrentUser) -> None:
    await ArtifactShareService(session).revoke(user_id=user.id, artifact_id=artifact_id)
    await session.commit()


@router.get("/{artifact_id}/download", response_class=Response)
async def download(
    artifact_id: UUID,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
    version: int | None = None,
    format: str = "auto",
) -> Response:
    """The artifact as a file.

    A picture for a poster and a PDF for a deck, because that is what each one
    is for: a poster goes into a message or onto a noticeboard, and a deck gets
    presented from and emailed around. The document is still available with
    `format=html`, and is what to keep if you ever want to edit it again.
    """
    artifact, chosen = await _load(session, artifact_id, user.id, version)
    name = _filename(artifact.title)
    spec = chosen.design_spec or {}
    width = int(spec.get("width") or 794)
    height = int(spec.get("height") or 1123)

    if format == "auto":
        format = _DOWNLOADS.get(artifact.kind, "png")

    if format == "html" or not settings.artifact_export_png:
        return Response(
            content=chosen.html,
            media_type="text/html; charset=utf-8",
            headers={
                **PUBLIC_HEADERS,
                "Content-Disposition": f'attachment; filename="{name}.html"',
            },
        )

    try:
        if format == "pdf":
            rendered, kind, suffix = (
                await to_pdf(chosen.html, width=width, height=height),
                "application/pdf",
                "pdf",
            )
        else:
            rendered, kind, suffix = (
                await to_png(chosen.html, width=width, height=height),
                "image/png",
                "png",
            )
    except RasterUnavailable as exc:
        raise ValidationError(str(exc)) from exc

    return Response(
        content=rendered,
        media_type=kind,
        headers={
            **PUBLIC_HEADERS,
            "Content-Disposition": f'attachment; filename="{name}.{suffix}"',
        },
    )


# What a download is, by kind, when nobody said. A game and a website are
# the file: a picture of either is one frame of something meant to be used.
_DOWNLOADS = {"slides": "pdf", "games": "html", "website": "html", "app": "html"}


def _filename(title: str) -> str:
    """A filename from a title, keeping only what every filesystem accepts."""
    kept = [c if c.isalnum() or c in " -_" else "-" for c in title.strip()]
    cleaned = "".join(kept).strip().replace(" ", "-")[:60]
    return cleaned or "artifact"


# -- anybody at all ------------------------------------------------------


@public_router.get("/{token}", response_class=Response, dependencies=[Depends(limit_share)])
async def shared(token: str, session: SessionDep, settings: SettingsDep) -> Response:
    """A shared artifact, to anyone with the link and no account.

    The only unauthenticated route in the app that returns a document. It
    carries the kind's own sandbox policy, so a poster served here is in an
    opaque origin and cannot do anything with the host it is served from.
    """
    public = await ArtifactShareService(session).view(token)
    await session.commit()
    kind = build_kinds(settings).get(public.kind)
    policy = kind.sandbox.csp if kind else "sandbox; default-src 'none'"
    return Response(
        content=public.html,
        media_type="text/html; charset=utf-8",
        headers={
            **PUBLIC_HEADERS,
            "Content-Security-Policy": policy,
            # The size it chose for itself. The page showing it cannot read
            # this out of the document — that is the whole point of the opaque
            # origin — so it is told here instead.
            "X-Artifact-Width": str(public.width),
            "X-Artifact-Height": str(public.height),
            # What it is and what it may do, for the same reason. A shared page
            # that framed every artifact with `sandbox=""` showed a game that
            # could not run and a website whose menu went nowhere.
            "X-Artifact-Kind": public.kind,
            "X-Artifact-Sandbox": kind.sandbox.iframe_sandbox if kind else "",
        },
    )
