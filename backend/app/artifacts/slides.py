"""The slides kind.

A deck is built in three jobs, because they are three different jobs and a
model asked to do all of them at once does the last one badly:

    outline   what the talk argues, and what each slide does for it
    design    how the deck looks: a palette, two faces, one stylesheet
    write     one call per slide, several at a time

The outline is where a deck is won or lost. Ten headings in a row is a table of
contents read aloud; a talk has a shape.

Slides are written concurrently and emitted in order. Out of order they arrive
as a jumble, and a deck that appears out of sequence is worse than one that
appears slowly.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from time import perf_counter

from app.artifacts.base import (
    ArtifactUnavailable,
    Brief,
    BuildUpdate,
    Built,
    Canvas,
    DesignSpec,
    Finished,
    Part,
    Plan,
    SandboxPolicy,
    Step,
    Swatch,
)
from app.artifacts.deck import Deck, document, one_slide
from app.artifacts.imagery import Photo, attach_photos, find_photo, variable_for
from app.artifacts.model import ArtifactModel, Written, strip_fence
from app.artifacts.slide_prompts import (
    DEFAULT_SLIDES,
    DESIGN_SYSTEM,
    MAX_SLIDES,
    MIN_SLIDES,
    OUTLINE_SYSTEM,
    SLIDE_SYSTEM,
)
from app.artifacts.validate import Finding
from app.tools.serpapi import SearchProvider

logger = logging.getLogger(__name__)

# 16:9 at a size that reads on a projector and prints without resampling.
WIDESCREEN = Canvas(width=1600, height=900, page="1600px 900px")
# How many slides are written at once. Three keeps the gateway comfortable and
# turns a three-minute deck into about a minute.
AT_ONCE = 3
_COUNT = re.compile(r"\b(\d{1,2})\s*(?:slides?|pages?)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Slide:
    heading: str
    layout: str
    job: str
    content: str
    speaker_notes: str = ""
    image_query: str = ""


def wanted_slides(brief: Brief) -> int:
    """How many slides, from what the person asked for.

    The tool has a field for it, and the brief is read as a fallback, because
    a number said in passing — "make me an 8 slide deck" — is a number the
    chat model will sometimes paraphrase away while still repeating it back.
    That happened on the first real run: it announced an eight-slide deck and
    made ten.
    """
    if brief.count:
        return max(MIN_SLIDES, min(MAX_SLIDES, brief.count))
    said = _COUNT.search(f"{brief.brief} {brief.title}")
    if not said:
        return DEFAULT_SLIDES
    return max(MIN_SLIDES, min(MAX_SLIDES, int(said.group(1))))


class SlidesKind:
    name = "slides"
    label = "Slides"
    description = (
        "A slide deck for presenting: a talk, a pitch, a lesson, a report read "
        "out to a room. Use it when the answer is a sequence someone will walk "
        "an audience through, rather than one thing to look at."
    )
    canvas = WIDESCREEN
    sandbox = SandboxPolicy(scripts=False, fonts=True, images=False)

    def __init__(
        self,
        model: ArtifactModel,
        *,
        max_bytes: int = 4_000_000,
        search: SearchProvider | None = None,
    ) -> None:
        self._model = model
        self._max_bytes = max_bytes
        self._search = search

    async def build(self, brief: Brief) -> AsyncIterator[BuildUpdate]:
        started = perf_counter()
        count = wanted_slides(brief)
        context = _context(brief)

        yield Step(label="Reading the brief", detail=brief.title)

        yield Step(label="Planning the talk", detail=f"{count} slides")
        outline, slides = await self._outline(context, count)
        if not slides:
            raise ArtifactUnavailable("Could not work out what the talk should say.")
        yield Plan(titles=tuple(slide.heading for slide in slides))
        yield Step(label="Planned", detail=outline.get("argument", "")[:90])

        yield Step(label="Choosing a look", detail="palette, type and layouts")
        deck, spec = await self._design(context, outline, count)
        yield Step(label="Chose a look", detail=_direction(spec))

        photos = await self._photographs(slides)
        if photos:
            yield Step(label="Found pictures", detail=f"{len(photos)} of them")

        # Filled as they are written; the generator yields what the panel
        # should show and leaves the pieces here.
        sections: dict[int, str] = {}
        async for update in self._write_slides(deck, slides, photos, count, sections):
            yield update

        html = document(deck, [sections[i] for i in sorted(sections)])
        if photos:
            html = attach_photos(html, [photo for _, photo in sorted(photos.items())])

        yield Step(label="Checking it fits")
        yield Finished(
            built=Built(
                html=html,
                spec=replace(spec, width=deck.width, height=deck.height),
                model=self._model.name,
                build_ms=int((perf_counter() - started) * 1000),
                findings=tuple(str(f) for f in self._check(html, len(sections), count)),
            )
        )

    # -- the three jobs --------------------------------------------------

    async def _outline(self, context: str, count: int) -> tuple[dict, list[Slide]]:
        asked = f"{context}\n\nThe deck has exactly {count} slides."
        answered = await self._model.decide(OUTLINE_SYSTEM, asked, max_tokens=4000)
        raw = answered.get("slides")
        if not isinstance(raw, list):
            return answered, []

        slides = [
            Slide(
                heading=str(item.get("heading") or "").strip()[:120],
                layout=str(item.get("layout") or "points").strip().lower()[:20],
                job=str(item.get("job") or "").strip()[:200],
                content=str(item.get("content") or "").strip()[:1500],
                speaker_notes=str(item.get("speaker_notes") or "").strip()[:600],
                image_query=str(item.get("image_query") or "").strip()[:200],
            )
            for item in raw[:count]
            if isinstance(item, dict)
        ]
        return answered, [slide for slide in slides if slide.heading]

    async def _design(self, context: str, outline: dict, count: int) -> tuple[Deck, DesignSpec]:
        layouts = ", ".join(sorted({str(s.get("layout", "")) for s in outline.get("slides", [])}))
        asked = (
            f"{context}\n\nThe talk argues: {outline.get('argument', '')}\n"
            f"It has {count} slides using these layouts: {layouts}\n"
            f"Each slide is exactly {self.canvas.width}px by {self.canvas.height}px."
        )
        answered = await self._model.decide(DESIGN_SYSTEM, asked, max_tokens=6000)

        css = str(answered.get("css") or "").strip()
        if not css:
            raise ArtifactUnavailable("The design model returned no stylesheet.")

        display = str(answered.get("display_font") or "Playfair Display").strip()
        body = str(answered.get("body_font") or "Work Sans").strip()
        spec = DesignSpec(
            movement=str(answered.get("movement") or "Plain Speaking"),
            rationale=str(answered.get("rationale") or ""),
            palette=_palette(css),
            display_font=display,
            body_font=body,
            width=self.canvas.width,
            height=self.canvas.height,
        )
        deck = Deck(
            title=str(outline.get("title") or "Deck")[:200],
            css=css,
            width=self.canvas.width,
            height=self.canvas.height,
            fonts=(display, body),
        )
        return deck, spec

    async def _photographs(self, slides: Sequence[Slide]) -> dict[int, Photo]:
        """One picture per slide that asked for one, as far as they are found."""
        if self._search is None:
            return {}
        wanted = [(i, s.image_query) for i, s in enumerate(slides) if s.image_query]
        if not wanted:
            return {}

        found: dict[int, Photo] = {}
        results = await asyncio.gather(
            *(find_photo(self._search, query) for _, query in wanted)
        )
        for (index, _), photo in zip(wanted, results, strict=True):
            if photo is not None:
                found[index] = photo
        return found

    async def _write_slides(
        self,
        deck: Deck,
        slides: Sequence[Slide],
        photos: dict[int, Photo],
        count: int,
        sections: dict[int, str],
    ) -> AsyncIterator[BuildUpdate]:
        """Every slide, written several at a time and reported in order."""
        next_to_report = 0
        limit = asyncio.Semaphore(AT_ONCE)

        async def write(index: int) -> tuple[int, str]:
            async with limit:
                return index, await self._one_slide(deck, slides[index], photos.get(index))

        pending = [asyncio.create_task(write(i)) for i in range(len(slides))]
        try:
            for finished in asyncio.as_completed(pending):
                index, section = await finished
                sections[index] = section
                # Held back until everything before it has arrived. Slides are
                # written at once and finish out of order; a deck that appears
                # out of sequence is worse than one that appears slowly.
                while next_to_report in sections:
                    yield Part(
                        index=next_to_report,
                        total=count,
                        title=slides[next_to_report].heading,
                        html=one_slide(deck, sections[next_to_report]),
                    )
                    yield Step(
                        label="Writing the slides",
                        detail=f"{next_to_report + 1} of {count}",
                    )
                    next_to_report += 1
        finally:
            for task in pending:
                task.cancel()

    async def _one_slide(self, deck: Deck, slide: Slide, photo: Photo | None) -> str:
        system = "\n".join(
            [
                SLIDE_SYSTEM,
                "",
                "THE STYLESHEET YOU ARE WRITING AGAINST",
                deck.css,
            ]
        )
        if photo is not None:
            system += (
                f"\n\nA photograph has been found for this slide, in the CSS variable "
                f"`{variable_for(0)}`. Use it with `background-image: var({variable_for(0)})`, "
                "`background-size: cover`. Put a scrim over it and keep every word "
                "readable against the darkest part of it. Never write an image URL."
            )

        asked = (
            f"Heading: {slide.heading}\n"
            f"Layout: {slide.layout}\n"
            f"Its job in the talk: {slide.job}\n"
            f"Speaker notes (put these in a <div class=\"speaker-notes\">): "
            f"{slide.speaker_notes}\n\n"
            f"The substance:\n{slide.content}"
        )
        written = Written()
        async for _ in self._model.write(system, asked, written, temperature=0.5):
            pass
        return _section_of(written.text, slide.layout)

    def _check(self, html: str, made: int, wanted: int) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        if made < wanted:
            findings.append(
                Finding(
                    f"Only {made} of {wanted} slides could be written",
                    "the rest were dropped rather than left half-finished",
                )
            )
        size = len(html.encode())
        if size > self._max_bytes:
            findings.append(
                Finding("The deck is too large", f"{size} bytes, the limit is {self._max_bytes}")
            )
        return tuple(findings)


# -- helpers -------------------------------------------------------------


def _context(brief: Brief) -> str:
    parts = [f'<brief type="title">{brief.title}</brief>', f"<brief>{brief.brief}</brief>"]
    if brief.style_hints.strip():
        parts.append(f'<brief type="style">{brief.style_hints}</brief>')
    if brief.data.strip():
        parts.append(
            '<brief type="facts">Use these exactly as written, and do not invent '
            f"alongside them:\n{brief.data}</brief>"
        )
    if brief.language:
        parts.append(f'<brief type="language">Write the deck in {brief.language}.</brief>')
    return "\n\n".join(parts)


def _section_of(text: str, layout: str) -> str:
    """The `<section>` the model returned, whatever it wrapped it in."""
    cleaned = strip_fence(text)
    match = re.search(r"<section\b[\s\S]*</section>", cleaned)
    if match:
        return match.group(0)
    # No section at all. Wrap what came back rather than dropping the slide;
    # the stylesheet still applies and the words are still there.
    return f'<section class="slide slide--{layout}">{cleaned}</section>'


def _palette(css: str) -> tuple[Swatch, ...]:
    """The colours the stylesheet actually declared, for the stored spec."""
    found = re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;", css)
    return tuple(Swatch(name=name, hex=value) for name, value in found[:8])


def _direction(spec: DesignSpec) -> str:
    swatches = " ".join(s.hex for s in spec.palette[:4])
    return f"{spec.movement} · {swatches}".strip(" ·")
