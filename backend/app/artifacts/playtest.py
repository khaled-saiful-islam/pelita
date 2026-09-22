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

import logging
from dataclasses import dataclass
from typing import Any

from app.artifacts.raster import LOAD_TIMEOUT_MS, RasterUnavailable, _ensure_browser

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


@dataclass(frozen=True, slots=True)
class Playtest:
    """What happened when the game was run."""

    errors: tuple[str, ...] = ()
    painted: bool = True
    loops: bool = True
    reached_network: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors and self.painted and self.loops

    def complaints(self) -> list[str]:
        """What to tell the model to fix, in the order worth fixing."""
        found: list[str] = []
        # An exception first: everything else is usually its consequence.
        found.extend(f"The game threw an error while running: {e}" for e in self.errors[:3])
        if not self.painted:
            found.append(
                "The game rendered nothing. Its surface stayed blank after more than "
                "a second, so either it never drew a first frame or it drew off-screen."
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
  return { painted, frames: window.__frames || 0 };
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
    error. It raises only when there is no browser to play in, and the caller
    decides whether shipping unplayed is acceptable.
    """
    browser = await _ensure_browser()
    context = await browser.new_context(
        viewport={"width": max(width, 1), "height": max(height, 1)},
    )
    page = await context.new_page()

    errors: list[str] = []
    blocked: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)[:300]))
    page.on(
        "console",
        lambda message: errors.append(message.text[:300]) if message.type == "error" else None,
    )

    async def refuse(route: Any) -> None:
        # The document is self-contained by contract. Anything it asks for is
        # either a mistake or a game phoning home, and both are worth knowing.
        url = route.request.url
        if not url.startswith("data:") and not url.startswith("about:"):
            blocked.append(url[:120])
        await route.abort()

    try:
        await page.route("**/*", refuse)
        await page.set_content(_counting(html), wait_until="load", timeout=LOAD_TIMEOUT_MS)
        await page.wait_for_timeout(SETTLE_MS)
        first = await page.evaluate(_PROBE)

        # Press things. Most games bind arrows or space, and a handler that
        # throws only does so once something is pressed.
        for key in KEYS:
            try:
                await page.keyboard.press(key, delay=20)
            except Exception:  # noqa: BLE001 - a key that cannot be sent is not a finding
                break
        await page.mouse.click(width // 2, height // 2)
        await page.wait_for_timeout(AFTER_INPUT_MS)
        second = await page.evaluate(_PROBE)

        return Playtest(
            errors=tuple(dict.fromkeys(errors))[:5],
            painted=bool(first["painted"] or second["painted"]),
            loops=second["frames"] > first["frames"],
            reached_network=tuple(dict.fromkeys(blocked))[:3],
        )
    except RasterUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - a page that will not even open is a finding
        logger.info("playtest could not run: %s", exc)
        return Playtest(errors=(f"The game would not open: {exc}"[:300],))
    finally:
        await context.close()
