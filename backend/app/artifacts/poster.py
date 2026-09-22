"""The poster kind.

A poster is a fixed A4 canvas of typography, colour and drawn shapes, composed
in three passes rather than one:

    direct    choose a named direction, before any layout exists
    compose   write the document from that direction
    refine    look again, and only take things away

The first pass is what stops every poster converging on the same look: a model
asked to design and lay out simultaneously reaches for the arrangement it has
seen most often. The last is Chanel's rule — before it leaves the house, take
one thing off — and it is explicitly forbidden from adding, because a second
pass that may add is how a considered poster becomes a busy one.

The words live in `poster_prompts.py`; this file is the machinery.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from time import perf_counter

from app.artifacts.base import (
    Brief,
    BuildUpdate,
    Built,
    Canvas,
    Chunk,
    DesignSpec,
    Finished,
    SandboxPolicy,
    Step,
    Swatch,
)
from app.artifacts.model import ArtifactModel, Written
from app.artifacts.poster_prompts import (
    COMPOSE_SYSTEM,
    DEFAULT_CANVAS,
    DIRECTION_SYSTEM,
    MAX_CANVAS,
    MIN_CANVAS,
    REFINE_SYSTEM,
)
from app.providers.base import Usage, UsageSource

logger = logging.getLogger(__name__)

A4_AT_96DPI = Canvas(width=794, height=1123, page="A4")


def _context(brief: Brief) -> str:
    """The brief, fenced.

    Everything here came from a person through a chat message. It is
    information about what to make, never instruction about how to behave, and
    wrapping it says so — the same reason retrieved pages are scanned before a
    contributor sees them.
    """
    parts = [f"<brief type=\"title\">{brief.title}</brief>", f"<brief>{brief.brief}</brief>"]
    if brief.style_hints.strip():
        parts.append(f'<brief type="style">{brief.style_hints}</brief>')
    if brief.data.strip():
        parts.append(
            '<brief type="facts">Use these exactly as written. Do not round, '
            f"rephrase or invent alongside them:\n{brief.data}</brief>"
        )
    if brief.language:
        parts.append(
            f'<brief type="language">Write the poster\'s own words in {brief.language}.</brief>'
        )
    return "\n\n".join(parts)


class PosterKind:
    name = "poster"
    label = "Poster"
    description = (
        "A poster, flyer, banner or invitation: a fixed-size visual where the "
        "design carries the message. Use it when someone wants something to "
        "look at or print, not something to read."
    )
    canvas = A4_AT_96DPI
    sandbox = SandboxPolicy(scripts=False, fonts=True, images=False)

    def __init__(self, model: ArtifactModel, *, refine: bool = True) -> None:
        self._model = model
        self._refine = refine

    async def build(self, brief: Brief) -> AsyncIterator[BuildUpdate]:
        started = perf_counter()
        context = _context(brief)

        yield Step(label="Reading the brief", detail=brief.title)

        spec = await self._direct(context)
        yield Step(label="Chose a direction", detail=_direction_summary(spec))

        yield Step(label="Composing")
        written = Written()
        async for piece in self._model.write(self._compose_system(spec), context, written):
            yield Chunk(text=piece)

        html, usage = written.text, written.usage
        if self._refine:
            yield Step(label="Refining")
            polished = Written()
            async for _ in self._model.write(
                REFINE_SYSTEM, _refine_request(context, html), polished, temperature=0.2
            ):
                pass
            # A refinement that came back empty or truncated is not an
            # improvement. The composed document is already good.
            if len(polished.text) > len(html) * 0.6:
                html = polished.text
                usage = _summed(usage, polished.usage)

        yield Finished(
            built=Built(
                html=html,
                spec=spec,
                model=self._model.name,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                build_ms=int((perf_counter() - started) * 1000),
            )
        )

    async def _direct(self, context: str) -> DesignSpec:
        raw = await self._model.decide(DIRECTION_SYSTEM, context)
        spec = DesignSpec.from_dict(raw)
        return _with_fallbacks(spec)

    def _compose_system(self, spec: DesignSpec) -> str:
        return "\n".join(
            [
                COMPOSE_SYSTEM,
                "",
                "THE DIRECTION YOU ARE COMPOSING",
                f"Movement: {spec.movement}",
                f"Why: {spec.rationale}",
                "Palette, as :root custom properties, exactly these names and values:",
                *(f"  --{_slug(s.name)}: {s.hex};" for s in spec.palette),
                f"Display face: {spec.display_font}",
                f"Body face: {spec.body_font}",
                f"Layout: {spec.layout}",
                f"Motif: {spec.motif}",
                f"Subtle reference: {spec.reference}",
                "",
                f"Canvas: exactly {spec.width}px by {spec.height}px. {spec.shape}",
            ]
        )


def _refine_request(context: str, html: str) -> str:
    return f"{context}\n\nTHE POSTER AS IT STANDS:\n\n{html}"


def _direction_summary(spec: DesignSpec) -> str:
    """What the panel says it chose. The movement name plus the colours is the
    shortest honest description of a direction."""
    swatches = " ".join(s.hex for s in spec.palette[:4])
    return f"{spec.movement} · {swatches}".strip(" ·") if spec.movement else swatches


def _slug(name: str) -> str:
    kept = [c.lower() if c.isalnum() else "-" for c in name.strip()]
    return "".join(kept).strip("-") or "colour"


def _summed(first: Usage, second: Usage) -> Usage:
    """A refined poster cost two calls. Reporting only the second prices it as
    half of what it was."""
    return Usage(
        prompt_tokens=first.prompt_tokens + second.prompt_tokens,
        completion_tokens=first.completion_tokens + second.completion_tokens,
        source=first.source if first.source == second.source else UsageSource.ESTIMATED,
    )


def _with_fallbacks(spec: DesignSpec) -> DesignSpec:
    """A direction good enough to compose from, whatever came back.

    Only empties are filled. The model chooses the faces, the palette and the
    shape — a fixed list of families would make every poster this app ever
    makes share a handful of them, which is the same failure as everyone
    reaching for Inter, only slower to notice.

    The model is asked for JSON and usually sends it. When it does not, a
    poster with a plain palette is a far better outcome than a failed request,
    and retrying the cheap call costs more time than it saves.
    """
    palette = spec.palette or (
        Swatch(name="ground", hex="#12151C"),
        Swatch(name="ink", hex="#EDE6D8"),
        Swatch(name="accent", hex="#C8963E"),
    )
    width, height = DEFAULT_CANVAS
    return replace(
        spec,
        movement=spec.movement or "Quiet Confidence",
        palette=palette,
        display_font=spec.display_font or "Playfair Display",
        body_font=spec.body_font or "Work Sans",
        # Clamped, not chosen: a runaway number produces a canvas the browser
        # will not lay out, and a zero produces nothing at all.
        width=_clamped(spec.width, width),
        height=_clamped(spec.height, height),
    )


def _clamped(value: int, fallback: int) -> int:
    if value <= 0:
        return fallback
    return max(MIN_CANVAS, min(MAX_CANVAS, value))
