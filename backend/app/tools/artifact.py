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
    Finished,
    Step,
)
from app.tools.base import (
    Drafting,
    Made,
    Making,
    Progress,
    ToolPresentation,
    ToolUnavailable,
    ToolUpdate,
)

logger = logging.getLogger(__name__)


class CreateArtifactTool:
    """One tool for every kind. The model picks the kind."""

    name = "create_artifact"
    presentation = ToolPresentation(
        running="Designing", done="Designed", noun="artifact"
    )

    def __init__(self, kinds: dict[str, ArtifactKind], *, language: str | None = None) -> None:
        self._kinds = kinds
        self._language = language

    @property
    def description(self) -> str:
        made = "; ".join(f"{kind.name} - {kind.description}" for kind in self._kinds.values())
        return (
            "Design something to look at rather than read: "
            f"{made} "
            "Call this when the value is in how it looks. Do not call it to "
            "format an answer that is really text, and do not write any HTML "
            "or CSS yourself - describe what is wanted and it gets designed."
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
            language=self._language,
        )

        yield Making(kind=kind.name, title=title)

        try:
            async for update in kind.build(brief):
                if isinstance(update, Step):
                    yield Progress(label=update.label, detail=update.detail)
                elif isinstance(update, Chunk):
                    yield Drafting(text=update.text)
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
