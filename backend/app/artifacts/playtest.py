"""Playing a game before anybody is shown it.

A poster can be checked by reading it. A game cannot: the thing that goes
wrong is a reference error on line 300 that only fires once the loop starts,
and no amount of parsing the document finds it. What finds it is running it.

So the browser that already exists for exporting pictures is asked to open the
game, let a few frames go by, press some keys, and report what the console
said. A game that throws on load, paints nothing, or dies the moment somebody
presses an arrow key is caught here rather than by the person who asked for it.

Three things make this safe to do with code a model wrote. The browser's own
sandbox stays on. Every request the page makes is refused, so a game cannot
reach the network from inside the build. And it gets its own context, thrown
away afterwards, so nothing it leaves behind reaches the next one.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.artifacts.raster import (
    LOAD_TIMEOUT_MS,
    RasterUnavailable,
    _ensure_browser,
    shutdown,
)

logger = logging.getLogger(__name__)

# Long enough for a requestAnimationFrame loop to run many times, short enough
# that it does not dominate the build. A game that is going to throw on its
# first frame throws well inside this.
SETTLE_MS = 1200
# After input. A crash from a keypress handler shows up immediately.
AFTER_INPUT_MS = 600
# The keys a game is most likely to bind. Pressed to find the handler that
# throws, not to play well.
KEYS = ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space", "Enter")
# The whole playtest, end to end. A game that blocks its own JavaScript thread
# blocks everything asked of the page after it -- including the probe, which
# has no timeout of its own and will simply never return. Without this bound a
# single wedged game holds the build, the SSE stream and the person's turn open
# indefinitely. That is a real one: a game generation sat for five minutes with
# Chromium still running and nothing coming back.
BUDGET_S = 25.0
# One probe. `page.evaluate` takes no timeout of its own -- passing one is a
# TypeError, which is how this was found -- so it is bounded from outside.
PROBE_S = 5.0
# Closing a context whose renderer is wedged can itself hang.
CLOSE_S = 5.0


@dataclass(frozen=True, slots=True)
class Playtest:
    """What happened when the game was run."""

    errors: tuple[str, ...] = ()
    painted: bool = True
    loops: bool = True
    reached_network: tuple[str, ...] = ()
    # The page stopped answering. Worse than an exception: an exception leaves
    # a usable tab, and this does not.
    froze: bool = False
    # Drawn is not the same as visible.
    on_screen: bool = True

    @property
    def ok(self) -> bool:
        return (
            not self.errors
            and self.painted
            and self.loops
            and self.on_screen
            and not self.froze
        )

    def complaints(self) -> list[str]:
        """What to tell the model to fix, in the order worth fixing."""
        found: list[str] = []
        if self.froze:
            found.append(
                "The game locked up the browser: it stopped answering and had to be "
                "killed. Something blocks the JavaScript thread -- a loop that never "
                "reaches its exit, or work done all at once instead of across frames. "
                "Every frame must return quickly and ask for the next one."
            )
        # An exception first: everything else is usually its consequence.
        found.extend(f"The game threw an error while running: {e}" for e in self.errors[:3])
        if not self.painted:
            found.append(
                "The game rendered nothing. Its surface stayed blank after more than "
                "a second, so either it never drew a first frame or it drew off-screen."
            )
        if not self.on_screen:
            found.append(
                "The game draws correctly but none of it is on screen: its surface "
                "measures zero by zero. Everything must sit inside one "
                "`<div class=\"canvas\">` with an explicit pixel width and height. "
                "A layout that expects the window to have a height collapses here, "
                "because the game is framed at its own size and has no viewport."
            )
        if not self.loops:
            found.append(
                "The game drew one frame and stopped. A game needs a loop that keeps "
                "running -- requestAnimationFrame calling itself, or a timer."
            )
        if self.reached_network:
            found.append(
                "The game tried to load something from the network "
                f"({self.reached_network[0]}). Everything it needs must be in the file."
            )
        return found


# The one exception the prompt makes to "everything is in the file": the two
# faces the design chose, which the game is explicitly told to link.
_FONTS = re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/")
# Chromium's wording for a request that was refused, which is this module's
# doing and never the game's.
# `Failed to fetch` is the same event seen from the other side: a request this
# module aborted, surfacing as a rejected promise rather than a console line.
_REFUSED = re.compile(
    r"net::ERR_FAILED|Failed to load resource|Failed to fetch|NetworkError",
    re.IGNORECASE,
)


_PROBE = """() => {
  // Two things worth knowing that the console cannot say: whether anything was
  // painted, and whether the painting is still happening.
  const surface = document.querySelector('canvas');
  let painted = false;
  if (surface) {
    try {
      const ctx = surface.getContext('2d');
      if (ctx && surface.width > 0 && surface.height > 0) {
        const data = ctx.getImageData(0, 0, surface.width, surface.height).data;
        for (let i = 3; i < data.length; i += 4) {
          if (data[i] !== 0) { painted = true; break; }
        }
      } else {
        painted = true;  // WebGL or similar: not readable this way, assume drawn.
      }
    } catch (e) {
      painted = true;  // Tainted or unreadable. Not evidence of a blank game.
    }
  } else {
    // A DOM game. Anything with size on screen counts.
    painted = [...document.body.querySelectorAll('*')].some((el) => {
      const b = el.getBoundingClientRect();
      return b.width > 8 && b.height > 8;
    });
  }
  // Drawn is not the same as visible. A game whose layout collapsed draws
  // every pixel correctly into a box measuring zero by zero.
  const stage = document.querySelector('.canvas') || surface || document.body;
  const box = stage.getBoundingClientRect();
  return {
    painted,
    frames: window.__frames || 0,
    onScreen: box.width > 1 && box.height > 1,
  };
}"""

# Counts the game's own loop, not the browser's.
#
# This is prepended to the document rather than injected with
# `add_init_script`, which runs at document-start of a navigation and is
# therefore wiped by `set_content` rewriting the document -- the counter came
# back `undefined` every time, and every game looked stopped.
#
# It counts calls the game makes, not frames the browser paints. A browser
# ticks whether or not anything is listening, so "did rAF fire" says nothing;
# "did the game ask for another frame" is the question. `setInterval` is
# wrapped too, because a game driven by a timer is still a running game.
_COUNTER = (
    "<script>(function(){window.__frames=0;"
    "var raf=window.requestAnimationFrame.bind(window);"
    "window.requestAnimationFrame=function(cb){window.__frames++;return raf(cb);};"
    "var si=window.setInterval.bind(window);"
    "window.setInterval=function(cb,ms){return si(function(){"
    "window.__frames++;if(typeof cb==='function'){cb();}},ms);};"
    "})();</script>"
)


def _counting(html: str) -> str:
    """The game with the counter in front of everything it runs."""
    lowered = html.lower()
    for anchor in ("<head>", "<html>", "<!doctype html>"):
        at = lowered.find(anchor)
        if at != -1:
            cut = at + len(anchor)
            return html[:cut] + _COUNTER + html[cut:]
    return _COUNTER + html


async def play(html: str, *, width: int, height: int) -> Playtest:
    """Open the game, let it run, prod it, and report.

    Never raises for a bad game -- a game that fails is a result, not an
    error, and a game that wedges the browser is the most important result
    there is. It raises only when there is no browser to play in, and the
    caller decides whether shipping unplayed is acceptable.
    """
    browser = await _ensure_browser()
    context = await browser.new_context(
        viewport={"width": max(width, 1), "height": max(height, 1)},
    )
    try:
        return await asyncio.wait_for(_run(context, html, width, height), BUDGET_S)
    except TimeoutError:
        # Not a crash and not a slow machine: the page stopped answering, which
        # for a browser game is the worst outcome and the one a person would
        # otherwise discover by closing the tab.
        logger.info("playtest passed its budget of %.0fs; treating as a freeze", BUDGET_S)
        return Playtest(froze=True, painted=False, loops=False)
    except RasterUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - a page that will not even open is a finding
        # A load that times out is almost always the same thing as passing the
        # budget: the document's own script is blocking the thread, so the page
        # never reaches `load`. Reported as a freeze, because "it would not
        # open" sends the model looking for a syntax error it does not have.
        if "Timeout" in str(exc):
            logger.info("playtest timed out loading; treating as a freeze")
            return Playtest(froze=True, painted=False, loops=False)
        logger.info("playtest could not run: %s", exc)
        return Playtest(errors=(f"The game would not open: {exc}"[:300],))
    finally:
        await _discard(context)


async def _run(context: Any, html: str, width: int, height: int) -> Playtest:
    """The playtest itself, always called inside a deadline."""
    page = await context.new_page()

    errors: list[str] = []
    blocked: list[str] = []
    def thrown(exc: Any) -> None:
        # Same rule as the console: a request this playtest refused is not an
        # error the game made. What it did wrong -- reaching the network at
        # all -- is reported once, as itself.
        text = str(exc)
        if _REFUSED.search(text):
            return
        errors.append(text[:300])

    page.on("pageerror", thrown)

    def console(message: Any) -> None:
        if message.type != "error":
            return
        # A request this playtest refused is not the game's fault. Chromium
        # logs `net::ERR_FAILED` for every blocked resource, and counting those
        # as errors sent a perfectly good game back to be "fixed" -- every
        # single time, because the prompt asks for a font `<link>` and this
        # used to abort it. The game reaching the network is still reported,
        # once, through `reached_network`.
        if _REFUSED.search(message.text):
            return
        errors.append(message.text[:300])

    page.on("console", console)

    async def refuse(route: Any) -> None:
        """Everything the document asks for, except the faces it was told to
        use.

        It is self-contained by contract, so anything else it wants is either
        a mistake or a game phoning home, and both are worth knowing. Its type
        is another matter: the prompt names Google Fonts as the one exception,
        and a playtest that blocks what the prompt asks for is testing a
        different game from the one that will be shipped -- one rendered
        entirely in the fallback face.
        """
        url = route.request.url
        if _FONTS.match(url):
            await route.continue_()
            return
        if not url.startswith("data:") and not url.startswith("about:"):
            blocked.append(url[:120])
        await route.abort()

    await page.route("**/*", refuse)
    await page.set_content(_counting(html), wait_until="load", timeout=LOAD_TIMEOUT_MS)
    await page.wait_for_timeout(SETTLE_MS)
    first = await asyncio.wait_for(page.evaluate(_PROBE), PROBE_S)

    # Press things. Most games bind arrows or space, and a handler that throws
    # only does so once something is pressed.
    for key in KEYS:
        try:
            await page.keyboard.press(key, delay=20)
        except Exception:  # noqa: BLE001 - a key that cannot be sent is not a finding
            break
    with contextlib.suppress(Exception):
        await page.mouse.click(width // 2, height // 2)
    await page.wait_for_timeout(AFTER_INPUT_MS)
    second = await asyncio.wait_for(page.evaluate(_PROBE), PROBE_S)

    return Playtest(
        errors=tuple(dict.fromkeys(errors))[:5],
        painted=bool(first["painted"] or second["painted"]),
        loops=second["frames"] > first["frames"],
        on_screen=bool(second.get("onScreen", True)),
        reached_network=tuple(dict.fromkeys(blocked))[:3],
    )


async def _discard(context: Any) -> None:
    """Throw the page away, even when it does not want to go.

    Closing a context whose renderer is wedged can hang as thoroughly as the
    page did. Left alone that leaks a browser process per bad game, which is
    how a container runs out of memory overnight. If it will not close, the
    whole browser goes and the next caller starts a fresh one.
    """
    try:
        await asyncio.wait_for(context.close(), CLOSE_S)
    except Exception:  # noqa: BLE001 - tidying up must never raise
        logger.info("a wedged page would not close; restarting the browser")
        with contextlib.suppress(Exception):
            await shutdown()
