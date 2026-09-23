"""The games kind.

A game is the first artifact here that executes. That changes two things and
nothing else.

The first is the sandbox, and the architecture already had a place for it:
`SandboxPolicy(scripts=True)` gives the frame `allow-scripts` *without*
`allow-same-origin`, so the game runs in an opaque origin -- no cookies, no
access to the page that framed it, no credentialed call to this API. The same
policy becomes the CSP when the file is served on its own.

The second is how it is checked. A poster is wrong in ways you can see by
reading it; a game is wrong in ways that only appear once the loop starts. So
it is played -- in a real browser, with the keys pressed -- and what the
console said comes back to the model as the next thing to fix. A game that
throws on load never reaches the person who asked for it.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
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
    Plan,
    SandboxPolicy,
    Step,
    Swatch,
)
from app.artifacts.game_prompts import (
    CHANGE_SYSTEM,
    DEFAULT_LEVELS,
    DESIGN_SYSTEM,
    FIX_SYSTEM,
    GAME_HEIGHT,
    GAME_WIDTH,
    MAX_LEVELS,
    WRITE_SYSTEM,
)
from app.artifacts.model import ArtifactModel, Written, strip_fence
from app.artifacts.playtest import Playtest, play
from app.artifacts.raster import RasterUnavailable
from app.artifacts.validate import Finding

logger = logging.getLogger(__name__)

PLAYFIELD = Canvas(width=GAME_WIDTH, height=GAME_HEIGHT, page=f"{GAME_WIDTH}px {GAME_HEIGHT}px")
LEVELS_MARKER = "---LEVELS---"
# Two goes at a fix. The first catches the reference error; the second catches
# what the first one broke. A third has never been the difference between a
# game that works and one that does not, and every go is a whole document.
FIX_ATTEMPTS = 2
_COUNT = re.compile(r"\b(\d{1,2})\s*(?:levels?|stages?|rounds?)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Design:
    """A game, decided before it is written."""

    name: str = ""
    loop: str = ""
    pressure: str = ""
    controls: str = ""
    palette: tuple[str, ...] = ()
    display_font: str = "Space Mono"
    body_font: str = "Work Sans"
    feel: str = ""
    levels: tuple[dict, ...] = field(default_factory=tuple)


def wanted_levels(brief: Brief) -> int:
    """How many levels, from what the person asked for.

    The same field a deck uses for its slides. A number said in passing is one
    the chat model paraphrases away while still repeating it back, which is why
    it is a field at all.
    """
    if brief.count:
        return max(1, min(MAX_LEVELS, brief.count))
    said = _COUNT.search(f"{brief.brief} {brief.title}")
    if not said:
        return DEFAULT_LEVELS
    return max(1, min(MAX_LEVELS, int(said.group(1))))


class GamesKind:
    name = "games"
    label = "Game"
    description = (
        "A small playable browser game: an arcade game, a puzzle, a quiz with "
        "a timer, a toy somebody can actually play. Use it when the answer is "
        "something to play rather than something to read or look at."
    )
    canvas = PLAYFIELD
    # The one kind here that executes. No `allow-same-origin`, so the game gets
    # an opaque origin and can reach neither a cookie nor this API.
    sandbox = SandboxPolicy(scripts=True, fonts=True, images=True)

    def __init__(
        self,
        model: ArtifactModel,
        *,
        max_bytes: int = 2_000_000,
        playtest: bool = True,
    ) -> None:
        self._model = model
        self._max_bytes = max_bytes
        self._playtest = playtest

    async def build(self, brief: Brief) -> AsyncIterator[BuildUpdate]:
        started = perf_counter()
        levels = wanted_levels(brief)
        context = _context(brief, levels)

        yield Step(label="Reading the brief", detail=brief.title)

        yield Step(label="Designing the game", detail="the loop, the pressure, the levels")
        design = await self._design(context, levels)
        spec = _spec_of(design)
        yield Designed(
            movement=design.name or brief.title,
            palette=tuple(swatch.hex for swatch in spec.palette),
            display_font=design.display_font,
            body_font=design.body_font,
            rationale=design.loop,
            width=self.canvas.width,
            height=self.canvas.height,
        )
        yield Step(label="Designed it", detail=design.loop[:90])
        # The levels by name, the way a deck announces its slides: the shape of
        # what is coming, before any of it exists.
        named = [
            str(level.get("name") or f"Level {i + 1}")
            for i, level in enumerate(design.levels)
        ]
        if named:
            yield Plan(titles=tuple(named))

        written = Written()
        async for update in self._write(
            _write_system(design, levels), context, written, label="Writing the game"
        ):
            yield update
        html = strip_fence(written.text).strip()
        if not html:
            raise ArtifactUnavailable("The game could not be written.")
        html = stage(html)

        findings = self._check(html)
        outcome: dict = {}
        async for update in self._make_it_run(html, findings, outcome):
            yield update
        html, findings, note = outcome["html"], outcome["findings"], outcome["note"]

        yield Step(label="Checking it fits")
        yield Finished(
            built=Built(
                html=html,
                spec=replace(spec, width=self.canvas.width, height=self.canvas.height),
                model=self._model.name,
                prompt_tokens=written.usage.prompt_tokens,
                completion_tokens=written.usage.completion_tokens,
                build_ms=int((perf_counter() - started) * 1000),
                findings=tuple(str(f) for f in findings),
                note=note,
            )
        )

    async def revise(
        self, *, html: str, spec: DesignSpec, instruction: str
    ) -> AsyncIterator[BuildUpdate]:
        """Change a game, then make sure it still runs.

        The whole document comes back rather than a find-and-replace. A game is
        one program: a patch that lands in the wrong branch of it does not fail
        loudly, it just stops working somewhere the person has not reached yet.
        Rewriting costs more and is checked by playing the result.
        """
        started = perf_counter()
        yield Step(label="Making the change", detail=instruction[:70])

        changed = Written()
        async for update in self._write(
            CHANGE_SYSTEM,
            f'<user_context type="change">{instruction}</user_context>\n\n'
            f"THE GAME:\n\n{html}",
            changed,
            label="Making the change",
            temperature=0.3,
        ):
            yield update

        updated = strip_fence(changed.text).strip()
        if updated:
            updated = stage(updated)
        if not updated:
            raise ArtifactUnavailable("That change came back empty. The game is as it was.")

        findings = self._check(updated)
        outcome: dict = {}
        async for update in self._make_it_run(updated, findings, outcome):
            yield update
        updated, findings, note = outcome["html"], outcome["findings"], outcome["note"]

        yield Finished(
            built=Built(
                html=updated,
                spec=spec,
                model=self._model.name,
                build_ms=int((perf_counter() - started) * 1000),
                findings=tuple(str(f) for f in findings),
                note=note,
            )
        )

    # --- making it run ---------------------------------------------------

    async def _make_it_run(
        self, html: str, findings: tuple[Finding, ...], outcome: dict
    ) -> AsyncIterator[BuildUpdate]:
        """Play it, fix what playing it found, and say so while it happens.

        A generator rather than a plain call, because playing a game takes
        seconds and repairing one takes a whole model round-trip. Done
        silently that is a minute with nothing on screen, which is
        indistinguishable from a stream that has died -- and was mistaken for
        exactly that.

        The result is left in `outcome`: the best document reached, what is
        still wrong with it, and a sentence for the person if it is being
        shown despite a problem.
        """

        def settle(document: str, left: tuple[Finding, ...], note: str) -> None:
            outcome["html"], outcome["findings"], outcome["note"] = document, left, note

        settle(html, findings, "")
        if not self._playtest:
            return

        for attempt in range(FIX_ATTEMPTS + 1):
            yield Step(
                label="Playing it" if attempt == 0 else "Playing it again",
                detail="pressing the keys to see what breaks",
            )
            try:
                result = await play(html, width=self.canvas.width, height=self.canvas.height)
            except RasterUnavailable:
                # No browser in this deployment. The game is shown unplayed
                # rather than withheld, and the person is told which it is.
                logger.info("no browser to playtest in; shipping unplayed")
                settle(html, findings, "This game was not test-run before you saw it.")
                return

            complaints = result.complaints()
            if not complaints:
                yield Step(label="It plays", detail="no errors, and it keeps running")
                settle(html, findings, "")
                return
            if attempt == FIX_ATTEMPTS:
                settle(
                    html,
                    findings + tuple(Finding(c) for c in complaints),
                    _survivable(result),
                )
                return

            yield Step(label="Fixing what broke", detail=complaints[0][:80])
            repaired = Written()
            async for _ in self._model.write(
                FIX_SYSTEM, _fix_request(html, complaints), repaired, temperature=0.1
            ):
                pass
            candidate = strip_fence(repaired.text).strip()
            if not candidate:
                settle(
                    html,
                    findings + tuple(Finding(c) for c in complaints),
                    _survivable(result),
                )
                return
            html = stage(candidate)
            findings = self._check(html)
            settle(html, findings, "")

    # --- what can be known without running it -----------------------------

    def _check(self, html: str) -> tuple[Finding, ...]:
        """The problems worth catching before spending a browser on them."""
        found: list[Finding] = []
        body = _script_of(html)

        if not html.lstrip().lower().startswith("<!doctype html"):
            found.append(Finding("The game is not a whole HTML document."))
        if "<script" not in html.lower():
            found.append(Finding("The game has no script, so there is no game."))
        if len(html.encode()) > self._max_bytes:
            found.append(Finding("The game is too large to store."))

        # A blocking loop does not fail, it hangs -- the tab stops answering and
        # the person closes it. Cheaper to refuse than to playtest.
        if re.search(r"while\s*\(\s*(?:true|1)\s*\)", body):
            found.append(Finding("A `while (true)` loop will freeze the page."))
        if re.search(r"for\s*\(\s*;\s*;\s*\)", body):
            found.append(Finding("A `for (;;)` loop will freeze the page."))
        if not re.search(r"requestAnimationFrame|setInterval|setTimeout", body):
            found.append(Finding("Nothing drives the game forward: there is no loop."))

        for banned, why in (
            (r"\bfetch\s*\(", "calls `fetch`"),
            (r"\bXMLHttpRequest\b", "uses `XMLHttpRequest`"),
            (r"\bimport\s*\(", "imports at runtime"),
            (r"\beval\s*\(", "calls `eval`"),
            (r"\bWebSocket\b", "opens a WebSocket"),
        ):
            if re.search(banned, body):
                found.append(Finding(f"The game {why}; it must be self-contained."))

        if re.search(r"<script[^>]+\bsrc\s*=", html, re.IGNORECASE):
            found.append(Finding("The game loads a script from elsewhere."))
        if not re.search(r"keydown|keyup|pointerdown|touchstart|click", body):
            found.append(Finding("Nothing reads any input, so the game cannot be played."))

        return tuple(found)

    # --- the calls --------------------------------------------------------

    async def _design(self, context: str, levels: int) -> Design:
        asked = f"{context}\n\nThe game has exactly {levels} level{'' if levels == 1 else 's'}."
        for attempt in range(2):
            written = Written()
            async for _ in self._model.write(DESIGN_SYSTEM, asked, written, temperature=0.7):
                pass
            design = _read_design(written.text)
            if design.loop and design.levels:
                return design
            logger.info("thin game design on attempt %d", attempt + 1)
        raise ArtifactUnavailable("Could not work out what this game should be.")

    async def _write(
        self,
        system: str,
        user: str,
        into: Written,
        *,
        label: str,
        temperature: float | None = None,
    ) -> AsyncIterator[BuildUpdate]:
        """One long call, narrated. A minute of silence reads as a hang."""
        written = 0
        last_said = 0.0
        yield Step(label=label, detail="")

        async for piece in self._model.write(system, user, into, temperature=temperature):
            written += len(piece)
            yield Chunk(text=piece)
            now = perf_counter()
            if now - last_said >= 0.5:
                last_said = now
                yield Step(label=label, detail=f"{written // 1000} KB so far")


def stage(html: str) -> str:
    """The game with its surface asserted, whatever its stylesheet says.

    A game is framed at its own size, so the document has no viewport to fill
    and `height: 100%` on a body whose html has no height resolves to nothing.
    The result is a game that draws correctly into a box measuring zero by
    zero: every pixel is right and none of them are on screen. That is a real
    one -- a snake game shipped with a blank panel and a playtest that called
    it clean.

    Appended at the end of the head so a later rule of equal specificity wins
    without `!important`, the same way a slide's size is restated after its
    design has had its say.
    """
    guard = (
        "<style>\n"
        "html, body { margin: 0; padding: 0; overflow: hidden; }\n"
        f"html, body {{ width: {GAME_WIDTH}px; height: {GAME_HEIGHT}px; }}\n"
        f".canvas {{ position: relative; width: {GAME_WIDTH}px; "
        f"height: {GAME_HEIGHT}px; overflow: hidden; box-sizing: border-box; }}\n"
        "</style>"
    )
    lowered = html.lower()
    at = lowered.rfind("</head>")
    if at != -1:
        return html[:at] + guard + html[at:]
    at = lowered.find("<body")
    if at != -1:
        return html[:at] + guard + html[at:]
    return guard + html


# --- reading what came back ------------------------------------------------


def _read_design(text: str) -> Design:
    """Header lines, a marker, then the levels as JSON.

    The levels are after a marker rather than inside a JSON object with
    everything else, for the reason the deck's stylesheet is: the prose fields
    are full of apostrophes and colons, and a model escaping all of it into one
    value gets it wrong often enough to lose the whole build.
    """
    cleaned = strip_fence(text)
    head, _, levels = cleaned.partition(LEVELS_MARKER)

    fields: dict[str, str] = {}
    wanted = {"NAME", "LOOP", "PRESSURE", "CONTROLS", "PALETTE", "DISPLAY", "BODY", "FEEL"}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().upper() in wanted:
            fields[key.strip().upper()] = value.strip()

    return Design(
        name=fields.get("NAME", "")[:80],
        loop=fields.get("LOOP", "")[:300],
        pressure=fields.get("PRESSURE", "")[:300],
        controls=fields.get("CONTROLS", "")[:200],
        palette=_hexes(fields.get("PALETTE", "")),
        display_font=fields.get("DISPLAY") or "Space Mono",
        body_font=fields.get("BODY") or "Work Sans",
        feel=fields.get("FEEL", "")[:200],
        levels=_read_levels(levels),
    )


_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def _hexes(line: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_HEX.findall(line)))[:6]


def _read_levels(text: str) -> tuple[dict, ...]:
    body = strip_fence(text).strip()
    start, end = body.find("["), body.rfind("]")
    if start == -1 or end <= start:
        return ()
    try:
        parsed = json.loads(body[start : end + 1])
    except ValueError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(item for item in parsed[:MAX_LEVELS] if isinstance(item, dict))


# The design lists its colours ground-first and does not name them, so the
# roles come from their order -- which is the order the prompt asks for.
_ROLES = ("ground", "ink", "accent", "highlight", "quiet", "warning")


def _named(palette: tuple[str, ...]) -> list[Swatch]:
    return [
        Swatch(name=_ROLES[i] if i < len(_ROLES) else f"colour-{i + 1}", hex=colour)
        for i, colour in enumerate(palette)
    ]


def _spec_of(design: Design) -> DesignSpec:
    return DesignSpec(
        movement=design.name or "Playable",
        rationale=design.feel,
        palette=tuple(_named(design.palette)),
        display_font=design.display_font,
        body_font=design.body_font,
        width=GAME_WIDTH,
        height=GAME_HEIGHT,
    )


# --- what the calls are told ------------------------------------------------


def _context(brief: Brief, levels: int) -> str:
    parts = [
        f'<brief type="title">{brief.title}</brief>',
        f"<brief>{brief.brief}</brief>",
        f'<brief type="levels">{levels}</brief>',
    ]
    if brief.style_hints.strip():
        parts.append(f'<brief type="style">{brief.style_hints}</brief>')
    if brief.data.strip():
        parts.append(
            '<brief type="rules">Use these exactly as written, and do not invent '
            f"alongside them:\n{brief.data}</brief>"
        )
    if brief.language:
        parts.append(
            f'<brief type="language">Any words the player reads are in {brief.language}.</brief>'
        )
    return "\n\n".join(parts)


def _write_system(design: Design, levels: int) -> str:
    """The writing prompt, with the game that was decided attached to it."""
    described = [
        WRITE_SYSTEM,
        "",
        "THE GAME YOU ARE WRITING",
        f"Name: {design.name}",
        f"The loop: {design.loop}",
        f"The pressure: {design.pressure}",
        f"Controls: {design.controls}",
        f"Feel: {design.feel}",
        f"Palette: {', '.join(design.palette)}",
        f"Faces: {design.display_font} for headings and numbers, {design.body_font} for the rest",
        "",
        f"THE {levels} LEVEL{'' if levels == 1 else 'S'}, with the numbers they were given",
        json.dumps(list(design.levels), indent=2),
    ]
    return "\n".join(described)


def _fix_request(html: str, complaints: list[str]) -> str:
    problems = "\n".join(f"- {c}" for c in complaints)
    return f"WHAT WENT WRONG WHEN IT RAN:\n{problems}\n\nTHE GAME:\n\n{html}"


def _survivable(result: Playtest) -> str:
    """One sentence for the person when a game is shown with a problem left."""
    if result.errors:
        return "This game hit an error while it was being tested. It may not play correctly."
    if not result.painted:
        return "This game did not draw anything when it was tested."
    if not result.loops:
        return "This game stopped after its first frame when it was tested."
    return ""


_SCRIPT = re.compile(r"<script\b[^>]*>([\s\S]*?)</script>", re.IGNORECASE)


def _script_of(html: str) -> str:
    """Everything inside the document's scripts, which is where a game lives."""
    return "\n".join(_SCRIPT.findall(html))
