"""Opening a website before anybody is shown it.

A website fails in ways a stylesheet does not announce. A script throws on
load and the menu never opens. A page comes out with nothing on it. A pricing
table is a comfortable 1100 pixels wide, which is fine on the desk it was
imagined on and on a phone scrolls the whole site sideways. None of that is in
the markup to be read; all of it is on screen the moment it is opened.

So it is opened, twice: at a desktop width, where every page is visited and
weighed, and at a phone's, where every page is visited again and measured
against the edge of the screen. What comes back names the part to fix -- the
shell, or a particular page -- because a website is written in parts and is
repaired the same way.

The same three rules as the game's playtest keep this safe: the browser's own
sandbox stays on, every request the page makes is refused except the two
faces it was told to load, and each run gets a context of its own that is
thrown away afterwards.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.artifacts.playtest import _FONTS, _REFUSED, _discard
from app.artifacts.raster import LOAD_TIMEOUT_MS, RasterUnavailable, _ensure_browser
from app.artifacts.website_prompts import SITE_HEIGHT, SITE_WIDTH

logger = logging.getLogger(__name__)

PHONE_WIDTH = 390
PHONE_HEIGHT = 844
# Long enough for fonts to arrive and the router to show the first page.
SETTLE_MS = 700
# After moving to a page: the router is synchronous, the entrance is not.
AFTER_ROUTE_MS = 250
# A page with less than this much to read is not a page.
EMPTY_BELOW = 80
# Both widths, every page. A site whose script blocks its own thread stops
# answering and would otherwise hold the build open for ever.
BUDGET_S = 45.0
PROBE_S = 5.0


@dataclass(frozen=True, slots=True)
class Wide:
    """Something wider than a phone, and where it lives."""

    page: str  # the page's slug, or "" for the header and footer
    what: str
    by: int


@dataclass(frozen=True, slots=True)
class SiteCheck:
    """What happened when the site was opened."""

    errors: tuple[str, ...] = ()
    reached_network: tuple[str, ...] = ()
    froze: bool = False
    missing: tuple[str, ...] = ()
    empty: tuple[str, ...] = ()
    wide: tuple[Wide, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.errors or self.froze or self.missing or self.empty or self.wide)

    def shell_complaints(self) -> list[str]:
        """What the shell -- its script, its header, its footer -- got wrong."""
        found: list[str] = []
        if self.froze:
            found.append(
                "The site locked up the browser: it stopped answering and had to be "
                "killed. Something in the script blocks the page -- a loop that never "
                "ends, or work done all at once. Every handler must return quickly."
            )
        # Pages carry no script, so every error is the shell's.
        found.extend(f"The site threw an error while running: {e}" for e in self.errors[:3])
        found.extend(
            f"At phone width ({PHONE_WIDTH}px), {w.what} in the header or footer runs "
            f"{w.by}px past the edge of the screen, so the whole site scrolls sideways."
            for w in self.wide
            if not w.page
        )
        if self.reached_network:
            found.append(
                "The site tried to load something from the network "
                f"({self.reached_network[0]}). Everything it needs must be in the file; "
                "the two Google Fonts faces are the only exception."
            )
        return found

    def page_complaints(self, slug: str) -> list[str]:
        found: list[str] = []
        if slug in self.missing:
            found.append("The page is missing: there is no element for it at all.")
        if slug in self.empty:
            found.append(
                "The page has almost nothing on it when it is shown. Every section it "
                "was planned with must be there, written out in full."
            )
        found.extend(
            f"At phone width ({PHONE_WIDTH}px), {w.what} runs {w.by}px past the edge "
            "of the screen, so the page scrolls sideways."
            for w in self.wide
            if w.page == slug
        )
        return found

    def pages_to_fix(self) -> list[str]:
        named = [*self.missing, *self.empty, *(w.page for w in self.wide if w.page)]
        return list(dict.fromkeys(named))

    def summary(self, slugs: Sequence[str]) -> list[str]:
        """Everything still wrong, for the panel."""
        return [
            *self.shell_complaints(),
            *(f"{slug}: {complaint}" for slug in slugs for complaint in self.page_complaints(slug)),
        ]


# Each page's weight, at the width it is designed for.
_WEIGH = """(slug) => {
  const page = document.querySelector('[data-page="' + slug + '"]');
  if (!page) return { exists: false };
  const box = page.getBoundingClientRect();
  const text = (page.innerText || '').replace(/\\s+/g, ' ').trim();
  return { exists: true, shown: box.height > 0, text: text.length };
}"""

# What runs past the edge of the screen, and is not simply a strip that scrolls
# inside a box of its own, a drawer tucked off-canvas, or something invisible.
# Only the outermost offender is named: its children are its consequence.
_WIDE = """() => {
  const edge = document.documentElement.clientWidth + 2;
  const found = [];
  const seen = new Set();
  for (const element of document.querySelectorAll('body *')) {
    const box = element.getBoundingClientRect();
    if (box.width === 0 || box.height === 0 || box.right <= edge) continue;
    const style = getComputedStyle(element);
    if (style.position === 'fixed' || style.visibility === 'hidden') continue;
    let excused = false;
    for (let up = element.parentElement; up && up !== document.body; up = up.parentElement) {
      const around = getComputedStyle(up);
      if (around.position === 'fixed' || around.opacity === '0') { excused = true; break; }
      if (around.overflowX !== 'visible' && up.getBoundingClientRect().right <= edge) {
        excused = true; break;
      }
    }
    if (excused || style.opacity === '0') continue;
    const parent = element.parentElement;
    if (parent && parent !== document.body && parent.getBoundingClientRect().right > edge) continue;
    const page = element.closest('[data-page]');
    const classes = Array.from(element.classList).slice(0, 2).join('.');
    const text = (element.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 40);
    const what = element.tagName.toLowerCase() + (element.id ? '#' + element.id : '') +
      (classes ? '.' + classes : '') + (text ? ' ("' + text + '")' : '');
    const key = (page ? page.getAttribute('data-page') : '') + what;
    if (seen.has(key)) continue;
    seen.add(key);
    const slug = page ? page.getAttribute('data-page') : '';
    found.push({ page: slug, what, by: Math.round(box.right - edge + 2) });
    if (found.length >= 6) break;
  }
  return found;
}"""

_GO = "(slug) => { location.hash = '#/' + slug; }"


async def check_site(html: str, slugs: Sequence[str]) -> SiteCheck:
    """Open the site at both widths, visit every page, and report.

    Never raises for a bad site -- a site that fails is a result. It raises
    only when there is no browser to open it in, and the caller decides
    whether showing it unchecked is acceptable.
    """
    browser = await _ensure_browser()
    errors: list[str] = []
    blocked: list[str] = []
    try:
        return await asyncio.wait_for(_run(browser, html, list(slugs), errors, blocked), BUDGET_S)
    except TimeoutError:
        logger.info("site check passed its budget of %.0fs; treating as a freeze", BUDGET_S)
        return SiteCheck(froze=True, errors=tuple(dict.fromkeys(errors))[:5])
    except RasterUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - a site that will not open is a finding
        if "Timeout" in str(exc):
            logger.info("site check timed out loading; treating as a freeze")
            return SiteCheck(froze=True)
        logger.info("site check could not run: %s", exc)
        return SiteCheck(errors=(f"The site would not open: {exc}"[:300],))


async def _run(
    browser: Any,
    html: str,
    slugs: list[str],
    errors: list[str],
    blocked: list[str],
) -> SiteCheck:
    desktop = await browser.new_context(viewport={"width": SITE_WIDTH, "height": SITE_HEIGHT})
    phone = await browser.new_context(
        viewport={"width": PHONE_WIDTH, "height": PHONE_HEIGHT},
        is_mobile=True,
        has_touch=True,
        device_scale_factor=2,
    )
    try:
        missing, empty = await _weigh(desktop, html, slugs, errors, blocked)
        wide = await _measure(phone, html, [s for s in slugs if s not in missing], errors, blocked)
    finally:
        await _discard(desktop)
        await _discard(phone)

    return SiteCheck(
        errors=tuple(dict.fromkeys(errors))[:5],
        reached_network=tuple(dict.fromkeys(blocked))[:3],
        missing=tuple(missing),
        empty=tuple(empty),
        wide=tuple(wide),
    )


async def open_page(
    context: Any,
    html: str,
    errors: list[str],
    blocked: list[str],
    dialogs: list[str] | None = None,
) -> Any:
    """A page with the document in it, listening for what goes wrong.

    Every request is refused but the two faces the prompt asks for and the
    document's own data URIs. A dialog -- `alert`, `confirm`, `prompt` -- is
    dismissed and, when asked, recorded: they are blocked in the frame the
    document is shown in, so one here is a question nobody will ever be
    asked.
    """
    page = await context.new_page()

    def thrown(exc: Any) -> None:
        text = str(exc)
        if not _REFUSED.search(text):
            errors.append(text[:300])

    def console(message: Any) -> None:
        # A request this check refused is not the site's error; reaching for
        # the network at all is reported once, as itself.
        if message.type == "error" and not _REFUSED.search(message.text):
            errors.append(message.text[:300])

    async def refuse(route: Any) -> None:
        url = route.request.url
        if _FONTS.match(url) or url.startswith("data:"):
            await route.continue_()
            return
        if not url.startswith("about:"):
            blocked.append(url[:120])
        await route.abort()

    async def dialog(opened: Any) -> None:
        if dialogs is not None:
            dialogs.append(str(opened.type))
        await opened.dismiss()

    page.on("pageerror", thrown)
    page.on("console", console)
    page.on("dialog", dialog)
    await page.route("**/*", refuse)
    await page.set_content(html, wait_until="load", timeout=LOAD_TIMEOUT_MS)
    await page.wait_for_timeout(SETTLE_MS)
    return page


async def _weigh(
    context: Any, html: str, slugs: list[str], errors: list[str], blocked: list[str]
) -> tuple[list[str], list[str]]:
    """Every page at desktop width: is it there, and is there anything on it."""
    page = await open_page(context, html, errors, blocked)
    missing: list[str] = []
    empty: list[str] = []
    for slug in slugs:
        await asyncio.wait_for(page.evaluate(_GO, slug), PROBE_S)
        await page.wait_for_timeout(AFTER_ROUTE_MS)
        weighed = await asyncio.wait_for(page.evaluate(_WEIGH, slug), PROBE_S)
        if not weighed.get("exists"):
            missing.append(slug)
        elif not weighed.get("shown") or int(weighed.get("text", 0)) < EMPTY_BELOW:
            empty.append(slug)
    return missing, empty


async def _measure(
    context: Any, html: str, slugs: list[str], errors: list[str], blocked: list[str]
) -> list[Wide]:
    """Every page at phone width, against the edge of the screen."""
    page = await open_page(context, html, errors, blocked)
    wide: dict[tuple[str, str], Wide] = {}
    for slug in slugs:
        await asyncio.wait_for(page.evaluate(_GO, slug), PROBE_S)
        await page.wait_for_timeout(AFTER_ROUTE_MS)
        for found in await asyncio.wait_for(page.evaluate(_WIDE), PROBE_S):
            item = Wide(page=str(found["page"]), what=str(found["what"]), by=int(found["by"]))
            wide.setdefault((item.page, item.what), item)
    return list(wide.values())[:8]
