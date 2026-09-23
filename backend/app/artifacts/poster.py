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
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from time import perf_counter

from app.artifacts.base import (
    ArtifactUnavailable,
    Brief,
    BuildUpdate,
    Built,
    Canvas,
    Chunk,
    Designed,
    DesignSpec,
    Finished,
    SandboxPolicy,
    Step,
    Swatch,
    read_queries,
)
from app.artifacts.edits import apply_edits, read_edits
from app.artifacts.imagery import (
    WANTS_A_PICTURE,
    Photo,
    attach_photos,
    detach_photos,
    drop_invented_images,
    find_photos,
    photo_brief,
    use_the_real_photograph,
)
from app.artifacts.model import ArtifactModel, Written
from app.artifacts.poster_prompts import (
    COMPOSE_SYSTEM,
    DEFAULT_CANVAS,
    DIRECTION_SYSTEM,
    EDIT_SYSTEM,
    IMAGE_QUERY_SYSTEM,
    MAX_CANVAS,
    MIN_CANVAS,
    REFINE_SYSTEM,
    REVISE_SYSTEM,
)
from app.artifacts.validate import Finding, check, repair_request
from app.providers.base import Usage, UsageSource
from app.tools.serpapi import SearchProvider

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

    def __init__(
        self,
        model: ArtifactModel,
        *,
        refine: bool = True,
        max_bytes: int = 1_500_000,
        search: SearchProvider | None = None,
    ) -> None:
        self._model = model
        self._refine = refine
        self._max_bytes = max_bytes
        # Without one, a poster is type, colour and drawn shape. With one, it
        # can also use a photograph somebody else took.
        self._search = search

    async def build(self, brief: Brief) -> AsyncIterator[BuildUpdate]:
        started = perf_counter()
        context = _context(brief)

        yield Step(label="Reading the brief", detail=brief.title)

        # Said before the call, not after it. Seven seconds of silence under a
        # step that has already finished reads as a hang.
        yield Step(label="Choosing a direction", detail="palette, type and shape")
        spec = await self._direct(context)
        # The look, so the panel can show what is being made in its own colours
        # while it is still being made. A poster has no pieces to show as they
        # land, so this is what stands in for a preview.
        yield Designed(
            movement=spec.movement,
            palette=tuple(swatch.hex for swatch in spec.palette),
            display_font=spec.display_font,
            body_font=spec.body_font,
            rationale=spec.rationale,
            width=spec.width,
            height=spec.height,
        )
        yield Step(label="Chose a direction", detail=_direction_summary(spec))

        photos: list[Photo] = []
        if spec.image_queries and self._search is not None:
            yield Step(
                label="Finding a photograph"
                if len(spec.image_queries) == 1
                else f"Finding {len(spec.image_queries)} photographs",
                detail=spec.image_queries[0],
            )
            photos = await find_photos(self._search, spec.image_queries)
            if not photos:
                # Not an error. A poster without the photograph it hoped for is
                # still a poster, and the model is simply not told about one.
                yield Step(label="No photograph fitted", detail="designing without one")
            else:
                spec = replace(spec, image_source=photos[0].source)
                yield Step(
                    label=f"Found {len(photos)} photograph{'' if len(photos) == 1 else 's'}",
                    detail=f"{photos[0].width}x{photos[0].height}",
                )

        written = Written()
        async for update in self._write(
            self._compose_system(spec, photos=photos), context, written, label="Composing"
        ):
            yield update

        html, usage = written.text, written.usage

        # `html` stays the model's own document for the whole pipeline. The
        # photograph is attached only to check the real thing and to finish,
        # because a base64 image costs more tokens than the entire poster and
        # a repair pass that carried one would pay for it twice.
        notes: list[str] = []

        def finished(document: str) -> str:
            settled, note = self._settle_images(document, photos)
            if note and note not in notes:
                notes.append(note)
            return settled

        yield Step(label="Checking it fits")
        findings = self._check(finished(html), spec)
        if findings:
            yield Step(label="Fixing a problem", detail=str(findings[0]))
            repaired = Written()
            async for _ in self._model.write(
                self._compose_system(spec), repair_request(html, findings), repaired,
                temperature=0.1,
            ):
                pass
            # Only if it is actually better. A repair that broke something else
            # is not an improvement, and the original at least renders.
            if repaired.text and len(self._check(finished(repaired.text), spec)) < len(
                findings
            ):
                html = repaired.text
                usage = _summed(usage, repaired.usage)
                findings = self._check(finished(html), spec)

        if self._refine:
            yield Step(label="Refining")
            polished = Written()
            async for update in self._write(
                REFINE_SYSTEM,
                _refine_request(context, html),
                polished,
                label="Refining",
                temperature=0.2,
                stream_document=False,
            ):
                yield update
            # A refinement that came back empty or truncated is not an
            # improvement. The composed document is already good.
            # Kept only if it is whole and did not break anything the
            # composed document had right. A refinement is a nicety; a
            # document that renders is not.
            if len(polished.text) > len(html) * 0.6 and not self._check(
                finished(polished.text), spec
            ):
                html = polished.text
                usage = _summed(usage, polished.usage)

        yield Finished(
            built=Built(
                html=finished(html),
                spec=spec,
                model=self._model.name,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                build_ms=int((perf_counter() - started) * 1000),
                # Whatever survived the repair. Recorded rather than raised:
                # a poster with one imperfection is worth far more to the
                # person who asked than a refusal.
                findings=tuple(str(finding) for finding in findings),
                note=" ".join(notes),
            )
        )

    async def _write(
        self,
        system: str,
        user: str,
        into: Written,
        *,
        label: str,
        temperature: float | None = None,
        stream_document: bool = True,
    ) -> AsyncIterator[BuildUpdate]:
        """One long call, narrated.

        A minute of silence is indistinguishable from a hang, so the step
        reports how much has been written as it arrives. Throttled to about
        twice a second: this is reassurance, not telemetry, and a step that
        changes on every token is a flicker.
        """
        written = 0
        last_said = 0.0
        started = perf_counter()
        yield Step(label=label, detail="")

        async for piece in self._model.write(system, user, into, temperature=temperature):
            written += len(piece)
            if stream_document:
                yield Chunk(text=piece)
            now = perf_counter()
            if now - last_said >= 0.5:
                last_said = now
                yield Step(label=label, detail=_written_so_far(written, now - started))

    def _check(self, document: str, spec: DesignSpec) -> tuple[Finding, ...]:
        return check(
            document, spec=spec, sandbox=self.sandbox, max_bytes=self._max_bytes
        )

    async def revise(
        self, *, html: str, spec: DesignSpec, instruction: str
    ) -> AsyncIterator[BuildUpdate]:
        """Change an existing poster, keeping the direction it already has.

        The direction step is skipped: it was settled when the poster was made,
        and re-deciding it is how "make the date bigger" comes back as a
        different poster. So is the refinement pass, because the person is
        already looking at the result and can ask again.
        """
        started = perf_counter()

        # Out before the model sees it, back in afterwards. A base64
        # photograph in the document costs more than every other part of this
        # request put together.
        plain, existing = detach_photos(html)

        photos: list[Photo] = []
        if self._search is not None and WANTS_A_PICTURE.search(instruction):
            queries = await self._image_queries(instruction, spec)
            if queries:
                yield Step(label="Finding pictures", detail=queries[0])
                photos = await find_photos(self._search, queries)
                if not photos:
                    yield Step(label="No photograph fitted", detail="changing without one")

        written = Written()
        request = (
            f'<user_context type="change">{instruction}</user_context>\n\n'
            f"THE POSTER AS IT STANDS:\n\n{plain}"
        )
        # Anything newly found joins whatever the poster already had, so
        # "add one more" adds one rather than replacing the lot.
        kept = [Photo(data_uri=uri, source="", width=0, height=0) for uri in existing]
        available = kept + photos

        system = f"{REVISE_SYSTEM}\n{self._direction_block(spec)}"
        if available:
            system = f"{system}\n\nTHE PICTURES\n{photo_brief(available)}"

        # Try to change part of it before offering to write a new one. A model
        # handed the whole poster returns a whole poster, and the person who
        # wanted a different background loses the layout they liked.
        yield Step(label="Making the change", detail=instruction[:70])
        revised, usage = await self._edit_in_place(plain, instruction, system, available)

        if revised is None:
            yield Step(label="Redrawing", detail="the change needs more than a patch")
            async for update in self._write(
                system, request, written, label="Redrawing", temperature=0.2
            ):
                yield update
            revised, usage = written.text, written.usage
        revised, note = self._settle_images(revised, available)

        yield Step(label="Checking it fits")
        findings = self._check(revised, spec)
        if findings:
            # A revision that arrived broken is not an improvement. The poster
            # they are looking at still works.
            logger.info("revision rejected: %s", findings[0])
            raise ArtifactUnavailable(
                f"That change came back with a problem: {findings[0]}. "
                "The poster has been left as it was."
            )

        yield Finished(
            built=Built(
                html=revised,
                spec=spec,
                model=self._model.name,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                build_ms=int((perf_counter() - started) * 1000),
                note=note,
            )
        )

    def _settle_images(self, document: str, photos: Sequence[Photo]) -> tuple[str, str]:
        """Make every picture in the document one that actually exists.

        A model told a variable holds the photograph still sometimes writes a
        stock URL of its own, and a model given no photograph at all writes one
        every time. With a picture in hand the URL is pointed at it; without
        one it is removed, because a poster falling back to its gradient is a
        poster, and refusing the whole change over a URL the model invented
        loses work the person asked for.
        """
        if photos:
            corrected, swapped = use_the_real_photograph(document)
            if swapped:
                logger.info("redirected %d invented image url(s) to the real one", swapped)
            return attach_photos(corrected, photos), ""

        corrected, dropped = drop_invented_images(document)
        if not dropped:
            return corrected, ""
        logger.info("dropped %d invented image url(s); none was found", dropped)
        return corrected, "No picture could be found, so this was done without one."

    async def _edit_in_place(
        self,
        document: str,
        instruction: str,
        system: str,
        photos: Sequence[Photo],
    ) -> tuple[str | None, Usage]:
        """Change the parts that were asked about, or say it cannot be done.

        Two attempts. An unmatched `find` is the failure mode every
        implementation of this has, and it is silent in most of them; here the
        model is told exactly which ones missed and gets one more go. Returning
        None means "this needs a rewrite", which is a real answer for a change
        that restructures the poster.
        """
        empty = Usage(prompt_tokens=0, completion_tokens=0, source=UsageSource.ESTIMATED)
        asked = (
            f'<user_context type="change">{instruction}</user_context>\n\n'
            f"THE DOCUMENT:\n\n{document}"
        )

        for attempt in range(2):
            answered = await self._model.decide(
                f"{EDIT_SYSTEM}\n{system}", asked, max_tokens=6000
            )
            if answered.get("rewrite"):
                return None, empty

            edits = read_edits(answered)
            if not edits:
                return None, empty

            edited, problems = apply_edits(document, edits)
            if not problems:
                logger.info("changed %d part(s) of the poster in place", len(edits))
                return edited, empty
            if attempt:
                logger.info("edits did not apply, rewriting instead: %s", problems[0])
                return None, empty

            # Named, not swallowed. A find that matches nothing is the one
            # failure this approach has, and silence is how it becomes a
            # change that appeared to work and did not.
            asked = (
                f"{asked}\n\nYour previous edits could not be applied:\n"
                + "\n".join(f"- {problem}" for problem in problems)
                + "\n\nCopy the text to find character for character out of the "
                "document above, and make sure each one appears exactly once."
            )
        return None, empty

    async def _image_queries(self, instruction: str, spec: DesignSpec) -> tuple[str, ...]:
        """What to search for, when a change sounds like it wants a picture.

        A second, small call rather than a keyword lifted out of the sentence:
        "add something behind the title" wants a photograph and names nothing
        to search for, and the poster's own subject is what makes the query.
        """
        asked = (
            f'<user_context type="change">{instruction}</user_context>\n'
            f'<user_context type="poster">{spec.movement}. {spec.layout} '
            f"{spec.motif} {spec.reference}</user_context>"
        )
        answered = await self._model.decide(IMAGE_QUERY_SYSTEM, asked, max_tokens=300)
        return read_queries(answered)

    async def _direct(self, context: str) -> DesignSpec:
        raw = await self._model.decide(DIRECTION_SYSTEM, context)
        spec = DesignSpec.from_dict(raw)
        return _with_fallbacks(spec)

    def _compose_system(self, spec: DesignSpec, *, photos: Sequence[Photo] = ()) -> str:
        parts = [COMPOSE_SYSTEM, self._direction_block(spec)]
        if photos:
            parts.append(f"\nTHE PICTURES\n{photo_brief(photos)}")
        return "\n".join(parts)

    def _direction_block(self, spec: DesignSpec) -> str:
        """The direction, written out for whichever prompt is using it."""
        return "\n".join(
            [
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


def _written_so_far(characters: int, seconds: float) -> str:
    """"4.2 KB in 18s". The number moving is the point; its precision is not."""
    return f"{characters / 1024:.1f} KB in {seconds:.0f}s"


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
