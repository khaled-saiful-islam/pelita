"""Using an app before anybody is shown it.

Loading an app proves very little. A task board renders perfectly and throws
the moment somebody presses "Add"; a converter works until a field is empty; a
wheel spins once and then never again. The failures live behind the controls,
so the check presses them.

The app is opened at a desktop width and used the way a first-time visitor
would, without knowing what it is for: every text field is given something
plausible to hold, Enter is pressed, and the buttons are pressed in turn.
Everything the console says comes back. Then it is opened again at a phone's
width and measured against the edge of the screen.

It is not a judgement of whether the app is any good -- only of whether
using it breaks it. Same safety as the other checks: the browser's own
sandbox, every request refused, a context of its own, thrown away after.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

from app.artifacts.playtest import _discard
from app.artifacts.raster import RasterUnavailable, _ensure_browser
from app.artifacts.sitetest import _WIDE, PHONE_HEIGHT, PHONE_WIDTH, open_page
from app.artifacts.web_app_prompts import APP_HEIGHT, APP_WIDTH

logger = logging.getLogger(__name__)

# How much of an app is pressed. Enough to reach the handlers that matter --
# add, remove, reset, the main action -- without the check becoming the build.
MAX_FIELDS = 4
MAX_PRESSES = 12
AFTER_PRESS_MS = 140
SETTLE_MS = 700
BUDGET_S = 40.0
PROBE_S = 5.0
# Each press is given this long to find its target. A button covered by a
# dialog the previous press opened is not a finding.
PRESS_TIMEOUT_MS = 800

# Something plausible for each kind of field, so a validator has a real value
# to accept rather than an empty one to reject.
SAMPLES = {
    "email": "aina@example.com",
    "number": "42",
    "tel": "0123456789",
    "url": "https://example.com",
    "search": "report",
    "password": "correct-horse-battery",
    "text": "Finish the report",
    "": "Finish the report",
}
_UNTYPED = {"checkbox", "radio", "range", "color", "file", "hidden", "submit", "button",
            "reset", "image", "date", "time", "datetime-local", "month", "week"}

_RENDERED = """() => ({
  text: (document.body.innerText || '').replace(/\\s+/g, ' ').trim().length,
  controls: document.querySelectorAll(
    'button, input, select, textarea, [role="button"], canvas, svg'
  ).length,
})"""


@dataclass(frozen=True, slots=True)
class AppCheck:
    """What happened when the app was used."""

    errors: tuple[str, ...] = ()
    reached_network: tuple[str, ...] = ()
    froze: bool = False
    blank: bool = False
    dialogs: tuple[str, ...] = ()
    wide: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.errors or self.froze or self.blank or self.dialogs or self.wide)

    def complaints(self) -> list[str]:
        """What to tell the model to fix, in the order worth fixing."""
        found: list[str] = []
        if self.froze:
            found.append(
                "The app locked up the browser while it was being used: it stopped "
                "answering and had to be killed. Something blocks the JavaScript "
                "thread -- a loop that never ends, or work done all at once. Every "
                "handler must return quickly."
            )
        found.extend(f"Using the app threw an error: {e}" for e in self.errors[:3])
        if self.blank:
            found.append(
                "The app showed nothing: no words and no controls on the page after "
                "it loaded. The interface must be in the HTML, inside "
                '`<main id="app">`, not waiting on something that never happens.'
            )
        if self.dialogs:
            found.append(
                f"The app opened a browser `{self.dialogs[0]}()` dialog. Those are "
                "blocked where the app is shown, so that question is never asked. "
                "Ask and confirm in the page instead."
            )
        found.extend(
            f"At phone width ({PHONE_WIDTH}px), {what}, so the app scrolls sideways."
            for what in self.wide[:3]
        )
        if self.reached_network:
            found.append(
                "The app tried to load something from the network "
                f"({self.reached_network[0]}). Everything it needs must be in the file; "
                "the two Google Fonts faces are the only exception."
            )
        return found


async def use_app(html: str) -> AppCheck:
    """Open the app, use it, measure it on a phone, and report.

    Never raises for a bad app -- an app that fails is a result. It raises
    only when there is no browser, and the caller decides whether showing it
    unchecked is acceptable.
    """
    browser = await _ensure_browser()
    errors: list[str] = []
    blocked: list[str] = []
    dialogs: list[str] = []
    try:
        return await asyncio.wait_for(
            _run(browser, html, errors, blocked, dialogs), BUDGET_S
        )
    except TimeoutError:
        logger.info("app check passed its budget of %.0fs; treating as a freeze", BUDGET_S)
        return AppCheck(froze=True, errors=tuple(dict.fromkeys(errors))[:5])
    except RasterUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - an app that will not open is a finding
        if "Timeout" in str(exc):
            logger.info("app check timed out loading; treating as a freeze")
            return AppCheck(froze=True)
        logger.info("app check could not run: %s", exc)
        return AppCheck(errors=(f"The app would not open: {exc}"[:300],))


async def _run(
    browser: Any, html: str, errors: list[str], blocked: list[str], dialogs: list[str]
) -> AppCheck:
    desktop = await browser.new_context(viewport={"width": APP_WIDTH, "height": APP_HEIGHT})
    phone = await browser.new_context(
        viewport={"width": PHONE_WIDTH, "height": PHONE_HEIGHT},
        is_mobile=True,
        has_touch=True,
        device_scale_factor=2,
    )
    try:
        page = await open_page(desktop, html, errors, blocked, dialogs)
        rendered = await asyncio.wait_for(page.evaluate(_RENDERED), PROBE_S)
        blank = int(rendered.get("text", 0)) < 12 and int(rendered.get("controls", 0)) == 0
        if not blank:
            await _use(page)

        small = await open_page(phone, html, errors, blocked, dialogs)
        found = await asyncio.wait_for(small.evaluate(_WIDE), PROBE_S)
        wide = tuple(
            f"{item['what']} runs {int(item['by'])}px past the edge of the screen"
            for item in found
        )
    finally:
        await _discard(desktop)
        await _discard(phone)

    return AppCheck(
        errors=tuple(dict.fromkeys(errors))[:5],
        reached_network=tuple(dict.fromkeys(blocked))[:3],
        blank=blank,
        dialogs=tuple(dict.fromkeys(dialogs))[:3],
        wide=wide,
    )


async def _use(page: Any) -> None:
    """Type into what can be typed into, press Enter, press every button.

    Every step is allowed to fail on its own: a field that vanished, a button
    covered by the dialog the last press opened. What is being looked for is
    what the app says when it is used, not whether a robot can use it well.
    """
    fields = page.locator(
        "input:visible, textarea:visible, select:visible"
    )
    count = min(await fields.count(), MAX_FIELDS)
    for index in range(count):
        field = fields.nth(index)
        with contextlib.suppress(Exception):
            tag = await field.evaluate("(e) => e.tagName.toLowerCase()")
            kind = ((await field.get_attribute("type")) or "").lower()
            if tag == "select":
                await field.select_option(index=1, timeout=PRESS_TIMEOUT_MS)
            elif kind in ("checkbox", "radio"):
                await field.check(timeout=PRESS_TIMEOUT_MS)
            elif kind not in _UNTYPED:
                await field.fill(SAMPLES.get(kind, SAMPLES["text"]), timeout=PRESS_TIMEOUT_MS)
    if count:
        with contextlib.suppress(Exception):
            await fields.first.press("Enter", timeout=PRESS_TIMEOUT_MS)
            await page.wait_for_timeout(AFTER_PRESS_MS)

    buttons = page.locator(
        'button:visible, [role="button"]:visible, input[type="submit"]:visible,'
        ' input[type="button"]:visible'
    )
    presses = min(await buttons.count(), MAX_PRESSES)
    for index in range(presses):
        with contextlib.suppress(Exception):
            await buttons.nth(index).click(timeout=PRESS_TIMEOUT_MS, no_wait_after=True)
            await page.wait_for_timeout(AFTER_PRESS_MS)
    with contextlib.suppress(Exception):
        await page.keyboard.press("Escape")
    await page.wait_for_timeout(SETTLE_MS // 2)
