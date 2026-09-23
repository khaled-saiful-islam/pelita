"""Events a turn emits.

Their own module because they are a contract, not turn logic: the API renders
them as SSE frames and the browser switches on them. Keeping them separate means
adding an event is a change here and in two `match` arms, rather than another
edit to the service.

Adding an event type is additive — a client that does not recognise one ignores
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.guards.base import GuardVerdict
from app.providers.base import FinishReason, ToolResult
from app.services.accounting_service import Accounting


@dataclass(frozen=True, slots=True)
class StartEvent:
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    title: str
    language: str | None = None


@dataclass(frozen=True, slots=True)
class GuardEventPayload:
    """A guard fired. Surfaced so the banner can explain itself rather than
    silently altering what the model sees."""

    source: str
    severity: str
    rules: tuple[str, ...]
    evidence: str


@dataclass(frozen=True, slots=True)
class ToolEvent:
    """Progress of a tool, so the UI can say what is happening and why the
    first token is taking a moment."""

    tool: str
    status: str  # running | done | failed
    label: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SourcesEvent:
    sources: tuple[ToolResult, ...]


@dataclass(frozen=True, slots=True)
class ImagesEvent:
    images: tuple[ToolResult, ...]


@dataclass(frozen=True, slots=True)
class DeltaEvent:
    text: str


@dataclass(frozen=True, slots=True)
class AccountingEvent:
    accounting: Accounting


@dataclass(frozen=True, slots=True)
class SuggestionsEvent:
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactStartEvent:
    """Something is being made. Sent before the first step, so the panel can
    open and say so rather than appearing fully formed a minute later."""

    kind: str
    title: str


@dataclass(frozen=True, slots=True)
class ArtifactStepEvent:
    """Which phase the build is in.

    Honest because the build genuinely has phases. A single opaque call would
    have nothing to report, and a progress bar that reports nothing is a lie
    with a nicer appearance.
    """

    label: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactDeltaEvent:
    """The document as it is written, for the source view."""

    text: str


@dataclass(frozen=True, slots=True)
class ArtifactPlanEvent:
    """The shape of what is coming, before any of it is made."""

    titles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactDesignEvent:
    """What it is going to look like, before it looks like anything."""

    movement: str
    palette: tuple[str, ...]
    display_font: str
    body_font: str
    rationale: str = ""
    width: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True)
class ArtifactPartEvent:
    """One piece of a multi-part artifact, ready to look at.

    A deck takes a minute or two. Showing slide one as soon as it
    exists turns that into something happening rather than something waited
    for.
    """

    index: int
    total: int
    title: str
    html: str


@dataclass(frozen=True, slots=True)
class ArtifactDoneEvent:
    artifact_id: UUID
    kind: str
    title: str
    version: int
    size_bytes: int
    width: int
    height: int
    # What the checks still found after the one repair. Shown quietly rather
    # than hidden: the poster is worth having, and the person should know.
    findings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactFailedEvent:
    message: str
    retryable: bool = True


@dataclass(frozen=True, slots=True)
class DoneEvent:
    finish_reason: FinishReason


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    message: str


ChatEvent = (
    StartEvent
    | GuardEventPayload
    | ToolEvent
    | SourcesEvent
    | ImagesEvent
    | DeltaEvent
    | AccountingEvent
    | SuggestionsEvent
    | ArtifactStartEvent
    | ArtifactStepEvent
    | ArtifactDeltaEvent
    | ArtifactPlanEvent
    | ArtifactDesignEvent
    | ArtifactPartEvent
    | ArtifactDoneEvent
    | ArtifactFailedEvent
    | DoneEvent
    | ErrorEvent
)


def guard_payload(verdict: GuardVerdict) -> GuardEventPayload:
    return GuardEventPayload(
        source=str(verdict.source),
        severity=verdict.severity.label,
        rules=verdict.rules,
        evidence=verdict.findings[0].evidence if verdict.findings else "",
    )
