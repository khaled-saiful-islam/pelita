"""Making an artifact, as a tool the model can call.

The model does not write the poster. It writes a brief — what the thing is for,
who it is for, what has to appear on it — and hands over. A separate model with
a much larger budget and a prompt full of design instruction does the making.

That split is the reason this file is short. Everything about how a poster is
designed lives in `artifacts/`, and everything about how a tool is run lives in
the chat service; this is the join.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.artifacts.base import (
    ArtifactKind,
    ArtifactUnavailable,
    Brief,
    Chunk,
    Designed,
    Finished,
    OpenArtifact,
    Part,
    Plan,
    Step,
)
from app.tools.base import (
    Drafting,
    Looks,
    Made,
    Making,
    Piece,
    Planned,
    Progress,
    ToolPresentation,
    ToolUnavailable,
    ToolUpdate,
)

logger = logging.getLogger(__name__)


def _as_count(value: Any) -> int:
    """A number the model sent, or nothing. Models write "8" and 8 equally."""
    try:
        return max(0, min(99, int(str(value).strip())))
    except (TypeError, ValueError):
        return 0


class CreateArtifactTool:
    """One tool for every kind. The model picks the kind."""

    name = "create_artifact"
    presentation = ToolPresentation(
        running="Designing", done="Designed", noun="artifact", failed="Could not design it"
    )

    def __init__(self, kinds: dict[str, ArtifactKind], *, language: str | None = None) -> None:
        self._kinds = kinds
        self._language = language

    @property
    def description(self) -> str:
        made = "; ".join(f"{kind.name} - {kind.description}" for kind in self._kinds.values())
        return (
            "Make something to look at rather than read: "
            f"{made} "
            "Call this whenever somebody asks for one of these, in any words - "
            "a poster, a flyer, a deck, slides, a presentation, a game, a "
            "website, a landing page, a homepage, an app, a calculator, a "
            "tracker, a to-do list, a spinner, a converter, a timer. Never "
            "write it out in the message instead: a list of slide headings in a "
            "chat reply is not a deck, and HTML or JavaScript in a chat reply is "
            "not a website or an app. Do not "
            "call it to format an answer that is really text, and do not write "
            "any HTML or CSS yourself - describe what is wanted and it gets "
            "designed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": sorted(self._kinds),
                    "description": "What to make.",
                },
                "title": {
                    "type": "string",
                    "description": "A short name for it, shown on the panel and in the file.",
                },
                "brief": {
                    "type": "string",
                    "description": (
                        "What it is for, who it is for, the occasion and the mood. "
                        "Prose, not code and not a layout. Everything the person "
                        "said that matters, plus what you can reasonably infer. "
                        "Never write HTML or CSS here."
                    ),
                },
                "style_hints": {
                    "type": "string",
                    "description": (
                        "Any look the person asked for in their own words - "
                        "colours, mood, an era, something to avoid. Leave empty "
                        "if they said nothing about it."
                    ),
                },
                "data": {
                    "type": "string",
                    "description": (
                        "Facts that must appear exactly as given: dates, times, "
                        "prices, addresses, names. Copied verbatim, never rounded "
                        "or rephrased."
                    ),
                },
                "count": {
                    "type": "integer",
                    "description": (
                        "How many pieces, when the person said a number - "
                        "'eight slides', 'a 12 page deck', 'a game with 3 "
                        "levels', 'a 4 page website'. Copy their number "
                        "exactly. Leave it out entirely when they did not "
                        "say. \"A slide\", \"a deck\", \"a game\" and "
                        "\"a website\" are not numbers - that is the word "
                        "'a', and it means they did not say."
                    ),
                },
            },
            "required": ["kind", "title", "brief"],
        }

    async def stream(self, **kwargs: Any) -> AsyncIterator[ToolUpdate]:
        name = str(kwargs.get("kind") or "").strip()
        kind = self._kinds.get(name)
        if kind is None:
            offered = ", ".join(sorted(self._kinds)) or "nothing"
            raise ToolUnavailable(f"There is no {name!r} to make. Available: {offered}.")

        title = str(kwargs.get("title") or "Untitled").strip()[:200]
        brief = Brief(
            kind=kind.name,
            title=title,
            brief=str(kwargs.get("brief") or "").strip(),
            style_hints=str(kwargs.get("style_hints") or "").strip(),
            data=str(kwargs.get("data") or "").strip(),
            count=_as_count(kwargs.get("count")),
            language=self._language,
        )

        yield Making(kind=kind.name, title=title)

        try:
            async for update in kind.build(brief):
                if isinstance(update, Step):
                    yield Progress(label=update.label, detail=update.detail)
                elif isinstance(update, Chunk):
                    yield Drafting(text=update.text)
                elif isinstance(update, Plan):
                    yield Planned(titles=update.titles)
                elif isinstance(update, Designed):
                    yield Looks(
                        movement=update.movement,
                        palette=update.palette,
                        display_font=update.display_font,
                        body_font=update.body_font,
                        rationale=update.rationale,
                        width=update.width,
                        height=update.height,
                    )
                elif isinstance(update, Part):
                    yield Piece(
                        index=update.index,
                        total=update.total,
                        title=update.title,
                        html=update.html,
                    )
                elif isinstance(update, Finished):
                    yield Made(kind=kind.name, title=title, built=update.built)
        except ArtifactUnavailable as exc:
            # A failed build degrades the turn; it does not end it. The model
            # answers in words and the panel says what went wrong.
            raise ToolUnavailable(str(exc)) from exc

    async def run(self, **kwargs: Any) -> list[Any]:
        """Nothing to cite. An artifact is shown, not referenced."""
        async for _ in self.stream(**kwargs):
            pass
        return []


class EditArtifactTool:
    """Changing the artifact the person is looking at.

    Offered only when there is one. That is what lets somebody type "make it
    warmer" into the same box they type everything else into, and have it mean
    the poster on screen rather than a new poster about warmth.
    """

    name = "edit_artifact"
    description = (
        "Change the artifact the person is currently looking at: its colours, "
        "its layout, its type, how much of something there is. Use this "
        "whenever they ask for a change and an artifact is open - never make a "
        "new one for a change to an existing one. Do not use it to fix a typo "
        "or a wrong number; they can edit words directly on it, which is "
        "instant, and you should tell them so instead."
    )
    presentation = ToolPresentation(
        running="Redrawing", done="Redrawn", noun="change", failed="Could not make that change"
    )
    # Read by the chat service, which offers this only when a turn has an
    # artifact open and hands it in.
    wants_open_artifact = True

    parameters = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": (
                    "The change, in the person's own terms and no wider than "
                    "they asked. Everything they did not mention stays as it is."
                ),
            }
        },
        "required": ["instruction"],
    }

    def __init__(self, kinds: dict[str, ArtifactKind]) -> None:
        self._kinds = kinds

    async def stream(self, **kwargs: Any) -> AsyncIterator[ToolUpdate]:
        open_artifact: OpenArtifact | None = kwargs.get("open_artifact")
        instruction = str(kwargs.get("instruction") or "").strip()
        if open_artifact is None:
            raise ToolUnavailable("There is nothing open to change.")
        if not instruction:
            raise ToolUnavailable("No change was described.")

        kind = self._kinds.get(open_artifact.kind)
        if kind is None or not hasattr(kind, "revise"):
            raise ToolUnavailable(f"A {open_artifact.kind} cannot be changed this way.")

        yield Making(kind=open_artifact.kind, title=open_artifact.title)
        try:
            async for update in kind.revise(
                html=open_artifact.html,
                spec=open_artifact.spec,
                instruction=instruction,
            ):
                if isinstance(update, Step):
                    yield Progress(label=update.label, detail=update.detail)
                elif isinstance(update, Chunk):
                    yield Drafting(text=update.text)
                elif isinstance(update, Finished):
                    yield Made(
                        kind=open_artifact.kind,
                        title=open_artifact.title,
                        built=update.built,
                        replaces=open_artifact.id,
                    )
        except ArtifactUnavailable as exc:
            raise ToolUnavailable(str(exc)) from exc

    async def run(self, **kwargs: Any) -> list[Any]:
        async for _ in self.stream(**kwargs):
            pass
        return []
