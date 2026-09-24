"""The app kind.

A small web app -- a calculator, a wheel of names, a task board -- as one
self-contained HTML file. It is built the way a game is, because it is the same
shape of thing: one program, designed first, written in one go, and proved by
being used rather than by being read.

Two things are new.

The first is memory. An app is the first artifact somebody puts data into, and
that data is theirs. The app never touches storage itself -- its frame has an
opaque origin, where `localStorage` throws -- but calls `PelitaStore`, which
`app_runtime` puts in front of it: in the panel, saves go by message to the
panel and on to the person's account; in a downloaded copy, to that browser.

The second is how it is checked. `apptest` opens it and uses it -- fills the
fields, presses Enter, presses the buttons -- at a desktop width, then measures
it on a phone. What broke goes back to the model, twice at most.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.artifacts.app_runtime import app_id_of, instrument, new_app_id
from app.artifacts.apptest import AppCheck, use_app
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
from app.artifacts.model import ArtifactModel, Written, strip_fence
from app.artifacts.raster import RasterUnavailable
from app.artifacts.validate import Finding
from app.artifacts.web_app_prompts import (
    APP_HEIGHT,
    APP_WIDTH,
    CHANGE_SYSTEM,
    DESIGN_SYSTEM,
    FIX_SYSTEM,
    WRITE_SYSTEM,
)

logger = logging.getLogger(__name__)

SCREEN = Canvas(width=APP_WIDTH, height=APP_HEIGHT, page=f"{APP_WIDTH}px {APP_HEIGHT}px")
# Two goes at a fix, for the game's reason: the first catches the error, the
# second catches what the first one broke.
FIX_ATTEMPTS = 2
_LINE = re.compile(r"^\s*([A-Z]+)\s*:\s*(.+?)\s*$")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
_SCRIPT = re.compile(r"<script\b(?![^>]*data-pelita)[^>]*>([\s\S]*?)</script>", re.IGNORECASE)
_ROLES = ("ground", "ink", "accent", "support", "quiet", "warning")
_FALLBACK = ("#f7f5f0", "#1c1b19", "#4d7c0f", "#e7e2d6", "#6b6760")


@dataclass(frozen=True, slots=True)
class Design:
    """An app, decided before it is written."""

    name: str = ""
    direction: str = ""
    job: str = ""
    audience: str = ""
    core: tuple[str, ...] = ()
    keeps: str = ""
    first: str = ""
    delight: str = ""
    keys: str = ""
    palette: tuple[str, ...] = _FALLBACK
    display_font: str = "Space Grotesk"
    body_font: str = "Work Sans"
    feel: str = ""


class AppKind:
    name = "app"
    label = "App"
    description = (
        "A small web app somebody uses: a calculator, a wheel of names or random "
        "picker, a task or kanban board, a budget or expense tracker, a habit "
        "tracker, a timer, a unit or tip converter, flashcards. Use it when the "
        "answer is a tool to use -- not pages to read (website) and not something "
        "to play with a score (games)."
    )
    canvas = SCREEN
    # Scripts to run, forms so a submit handler ever hears about a submit.
    # No `allow-same-origin`: it cannot reach a cookie, the page around it, or
    # this API -- which is why the panel saves on its behalf.
    sandbox = SandboxPolicy(scripts=True, fonts=True, images=True, forms=True)

    def __init__(
        self,
        model: ArtifactModel,
        *,
        max_bytes: int = 1_500_000,
        check: bool = True,
    ) -> None:
        self._model = model
        self._max_bytes = max_bytes
        self._check_in_browser = check

    async def build(self, brief: Brief) -> AsyncIterator[BuildUpdate]:
        started = perf_counter()
        context = _context(brief)

        yield Step(label="Reading the brief", detail=brief.title)
        yield Step(label="Designing the app", detail="what it does, what it keeps, how it feels")
        design = await self._design(context)
        spec = _spec_of(design)
        yield Designed(
            movement=design.direction or design.name or brief.title,
            palette=design.palette,
            display_font=design.display_font,
            body_font=design.body_font,
            rationale=design.job or design.feel,
            width=APP_WIDTH,
            height=APP_HEIGHT,
        )
        # What you will be able to do in it, the way a deck announces slides.
        if design.core:
            yield Plan(titles=design.core)
        yield Step(label="Designed it", detail=design.job[:90])

        written = Written()
        request = context
        html = ""
        # Twice at most. An app near the size budget can run out of room before
        # `</html>`: it ends mid-script, does nothing, and would otherwise be
        # sent to a repair that runs out of room in the same place.
        for attempt in range(2):
            written = Written()
            async for update in self._narrate(
                _write_system(design), request, written, label="Building the app"
            ):
                yield update
            html = strip_fence(written.text).strip()
            if _finished(html):
                break
            logger.info("app came back unfinished on attempt %d", attempt + 1)
            request = context + _TIGHTER
            yield Step(label="Writing it again, tighter", detail="the first one ran out of room")
        if not html:
            raise ArtifactUnavailable("The app could not be written.")
        if not _finished(html):
            raise ArtifactUnavailable(
                "The app was too large to finish writing. Ask for fewer features at once."
            )
        html = instrument(html, new_app_id())

        outcome: dict[str, Any] = {}
        async for update in self._make_it_work(html, self._static(html), outcome):
            yield update
        html, findings, note = outcome["html"], outcome["findings"], outcome["note"]

        yield Finished(
            built=Built(
                html=html,
                spec=spec,
                model=self._model.name,
                prompt_tokens=written.usage.prompt_tokens,
                completion_tokens=written.usage.completion_tokens,
                build_ms=int((perf_counter() - started) * 1000),
                findings=tuple(str(f) for f in findings),
                note=note,
                summary=_summary(design),
            )
        )

    async def revise(
        self, *, html: str, spec: DesignSpec, instruction: str
    ) -> AsyncIterator[BuildUpdate]:
        """Change an app, then use it again.

        The whole document comes back rather than a find-and-replace: an app is
        one program, and a patch that lands in the wrong branch of it does not
        fail loudly, it quietly stops a button working. The id is kept, so a
        downloaded copy still finds what it saved.
        """
        started = perf_counter()
        keep = app_id_of(html)
        yield Step(label="Making the change", detail=instruction[:70])

        changed = Written()
        async for update in self._narrate(
            CHANGE_SYSTEM,
            f'<user_context type="change">{instruction}</user_context>\n\nTHE APP:\n\n{html}',
            changed,
            label="Making the change",
            temperature=0.3,
        ):
            yield update
        updated = strip_fence(changed.text).strip()
        if not updated:
            raise ArtifactUnavailable("That change came back empty. The app is as it was.")
        if not _finished(updated):
            raise ArtifactUnavailable(
                "That change came back unfinished, so it was not applied. The app is as it was."
            )
        updated = instrument(updated, keep)

        outcome: dict[str, Any] = {}
        async for update in self._make_it_work(updated, self._static(updated), outcome):
            yield update

        yield Finished(
            built=Built(
                html=outcome["html"],
                spec=spec,
                model=self._model.name,
                build_ms=int((perf_counter() - started) * 1000),
                findings=tuple(str(f) for f in outcome["findings"]),
                note=outcome["note"],
            )
        )

    # --- using it -------------------------------------------------------

    async def _make_it_work(
        self, html: str, findings: tuple[Finding, ...], outcome: dict[str, Any]
    ) -> AsyncIterator[BuildUpdate]:
        """Use it, fix what using it found, and say so while it happens."""

        def settle(document: str, left: tuple[Finding, ...], note: str) -> None:
            outcome["html"], outcome["findings"], outcome["note"] = document, left, note

        settle(html, findings, "")
        if not self._check_in_browser:
            return

        keep = app_id_of(html)
        for attempt in range(FIX_ATTEMPTS + 1):
            yield Step(
                label="Trying it out" if attempt == 0 else "Trying it again",
                detail="typing into it, pressing its buttons, on a desktop and a phone",
            )
            try:
                result = await use_app(html)
            except RasterUnavailable:
                logger.info("no browser to try the app in; shipping untried")
                settle(html, findings, "This app was not tried in a browser before you saw it.")
                return

            complaints = [*result.complaints(), *(str(f) for f in findings)]
            if not complaints:
                yield Step(label="It works", detail="no errors, on a desktop or a phone")
                settle(html, (), "")
                return
            if attempt == FIX_ATTEMPTS:
                settle(
                    html,
                    tuple(Finding(c) for c in result.complaints()) + findings,
                    _survivable(result),
                )
                return

            yield Step(label="Fixing what broke", detail=complaints[0][:90])
            repaired = Written()
            # Narrated like the first write: a repair is the whole app again,
            # a minute or more, and a minute with nothing moving on screen was
            # read as the build having died.
            async for update in self._narrate(
                FIX_SYSTEM,
                _fix_request(html, complaints),
                repaired,
                label="Rewriting it",
                temperature=0.1,
            ):
                yield update
            candidate = strip_fence(repaired.text).strip()
            # A repair that ran out of room is worse than the app it repairs.
            if not _finished(candidate):
                settle(html, tuple(Finding(c) for c in complaints), _survivable(result))
                return
            html = instrument(candidate, keep)
            findings = self._static(html)
            settle(html, findings, "")

    def _static(self, html: str) -> tuple[Finding, ...]:
        """What can be known without a browser, and is worth fixing anyway."""
        found: list[Finding] = []
        body = "\n".join(_SCRIPT.findall(html))
        if not html.lstrip().lower().startswith("<!doctype html"):
            found.append(Finding("The app is not a whole HTML document."))
        if not re.search(r"<main\b[^>]*\bid\s*=\s*[\"']app[\"']", html, re.IGNORECASE):
            found.append(Finding('Everything must live inside `<main id="app">`.'))
        if len(html.encode()) > self._max_bytes:
            found.append(Finding("The app is too large to store."))
        for banned, why in (
            (r"\bfetch\s*\(", "calls `fetch`"),
            (r"\bXMLHttpRequest\b", "uses `XMLHttpRequest`"),
            (r"\bWebSocket\b", "opens a WebSocket"),
            (r"\beval\s*\(", "calls `eval`"),
            (r"\b(?:localStorage|sessionStorage|indexedDB)\b", "uses browser storage directly"),
            (r"\bdocument\.cookie\b", "reads or writes cookies"),
            (r"(?<![\w.])(?:window\.)?(?:alert|confirm|prompt)\s*\(", "opens a browser dialog"),
            (r"while\s*\(\s*(?:true|1)\s*\)", "has a `while (true)` loop"),
            (r"for\s*\(\s*;\s*;\s*\)", "has a `for (;;)` loop"),
        ):
            if re.search(banned, body):
                found.append(Finding(f"The app {why}, which will not work where it is shown."))
        if re.search(r"<script[^>]+\bsrc\s*=", html, re.IGNORECASE):
            found.append(Finding("The app loads a script from elsewhere."))
        return tuple(found)

    # --- the calls --------------------------------------------------------

    async def _design(self, context: str) -> Design:
        for attempt in range(2):
            written = Written()
            async for _ in self._model.write(DESIGN_SYSTEM, context, written, temperature=0.7):
                pass
            design = read_design(written.text)
            if design.job and design.core:
                return design
            logger.info("thin app design on attempt %d", attempt + 1)
        raise ArtifactUnavailable("Could not work out what this app should do.")

    async def _narrate(
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


# --- reading what came back ------------------------------------------------


def read_design(text: str) -> Design:
    """The design, from one `KEY: value` line each. Tolerant: a missing line is
    a plainer app, never a failed one."""
    lines: dict[str, str] = {}
    for line in strip_fence(text).splitlines():
        matched = _LINE.match(line)
        if matched:
            lines[matched.group(1)] = matched.group(2)

    palette = tuple(dict.fromkeys(_HEX.findall(lines.get("PALETTE", ""))))[:6]
    core = tuple(
        part.strip()[:60] for part in lines.get("CORE", "").split("|") if part.strip()
    )[:6]
    return Design(
        name=lines.get("NAME", "")[:80],
        direction=lines.get("DIRECTION", "")[:80],
        job=lines.get("JOB", "")[:240],
        audience=lines.get("FOR", "")[:160],
        core=core,
        keeps=lines.get("KEEPS", "")[:200],
        first=lines.get("FIRST", "")[:240],
        delight=lines.get("DELIGHT", "")[:240],
        keys=lines.get("KEYS", "")[:160],
        palette=palette if len(palette) >= 3 else _FALLBACK,
        display_font=_face(lines.get("DISPLAY"), "Space Grotesk"),
        body_font=_face(lines.get("BODY"), "Work Sans"),
        feel=lines.get("FEEL", "")[:240],
    )


def _face(value: str | None, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", "", value or "").strip()[:40]
    return cleaned or fallback


def _spec_of(design: Design) -> DesignSpec:
    return DesignSpec(
        movement=design.direction or design.name or "App",
        rationale=design.feel or design.job,
        palette=tuple(
            Swatch(name=_ROLES[i] if i < len(_ROLES) else f"colour-{i + 1}", hex=colour)
            for i, colour in enumerate(design.palette)
        ),
        display_font=design.display_font,
        body_font=design.body_font,
        width=APP_WIDTH,
        height=APP_HEIGHT,
        shape="responsive",
    )


def _summary(design: Design) -> str:
    what = f"an app called {design.name}" if design.name else "an app"
    remembers = design.keeps and design.keeps.strip().lower() not in ("nothing", "none")
    kept = f"; it remembers {design.keeps} on the person's account" if remembers else ""
    return f"{what}: {design.job}{kept}" if design.job else what


def _context(brief: Brief) -> str:
    parts = [
        f'<brief type="title">{brief.title}</brief>',
        f"<brief>{brief.brief}</brief>",
    ]
    if brief.style_hints.strip():
        parts.append(f'<brief type="style">{brief.style_hints}</brief>')
    if brief.data.strip():
        parts.append(
            '<brief type="rules">Use these exactly as written, and do not invent '
            f"anything that contradicts them:\n{brief.data}</brief>"
        )
    if brief.language:
        parts.append(
            f'<brief type="language">Every word a person reads is in {brief.language}.</brief>'
        )
    return "\n\n".join(parts)


def _write_system(design: Design) -> str:
    """The writing prompt, with the app that was decided attached to it."""
    lines = [
        WRITE_SYSTEM,
        "",
        "THE APP YOU ARE WRITING",
        f"Name: {design.name}",
        f"Look: {design.direction} -- {design.feel}",
        f"The job: {design.job}",
        f"For: {design.audience}",
        "What somebody does in it: " + "; ".join(design.core),
        f"What it keeps between visits: {design.keeps or 'nothing'}",
        f"The first screen: {design.first}",
        f"The detail that shows care: {design.delight}",
        f"Keyboard: {design.keys or 'Enter and Escape'}",
        f"Palette: {', '.join(design.palette)}",
        f"Faces: {design.display_font} for headings and numbers, {design.body_font} for text",
    ]
    return "\n".join(line for line in lines if not line.rstrip().endswith(":"))


_TIGHTER = (
    "\n\nThe last attempt ran out of room before `</html>`. Write it again, "
    "complete, in well under 40 KB: fewer variations, no repeated rules, "
    "nothing the design did not name."
)


def _finished(html: str) -> bool:
    """Whether the document reached its own end rather than being cut off."""
    tail = html.rstrip().lower()
    return tail.endswith("</html>") and "</script>" in tail


def _fix_request(html: str, complaints: list[str]) -> str:
    problems = "\n".join(f"- {c}" for c in complaints)
    return f"WHAT WENT WRONG WHEN IT WAS USED:\n{problems}\n\nTHE APP:\n\n{html}"


def _survivable(result: AppCheck) -> str:
    """One sentence for the person when an app is shown with a problem left."""
    if result.froze:
        return "This app stopped responding when it was tried. Some of it may not work."
    if result.errors:
        return "This app hit an error when it was tried. Some of it may not work."
    if result.blank:
        return "This app showed nothing when it was tried."
    if result.dialogs:
        return "This app asks a question in a way the panel cannot show."
    if result.wide:
        return "Part of this app is wider than a phone screen."
    return ""

