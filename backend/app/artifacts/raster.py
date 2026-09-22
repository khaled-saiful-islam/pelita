"""Turning a poster into a picture.

A poster is an HTML document, which is the right thing for it to be — it
prints, it shares, it can be edited a word at a time. It is the wrong thing to
put in a WhatsApp message, and that is where most posters end up.

So there is a real browser here. Nothing else renders a document the way the
browser the person is looking at does, and a poster exported through an
approximation is a poster with the letter-spacing subtly wrong.

The browser is started once and kept. Launching one per request adds about a
second to every export and a process to every concurrent one.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_browser: Any = None
_playwright: Any = None
_lock = asyncio.Lock()

# The document has to be given time to fetch its fonts, and then time to lay
# itself out with them. Measured against real posters, not guessed.
FONT_SETTLE_MS = 400
LOAD_TIMEOUT_MS = 15_000


class RasterUnavailable(RuntimeError):
    """No browser, so no picture. The document itself is still available."""


async def _ensure_browser() -> Any:
    """The shared browser, started on first use."""
    global _browser, _playwright
    async with _lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - depends on the image
            raise RasterUnavailable(
                "This deployment cannot export pictures. Download the file instead."
            ) from exc
        try:
            _playwright = await async_playwright().start()
            # The browser's own sandbox stays on. What is rendered here is a
            # document a model wrote, and turning the sandbox off to make it
            # start in a container means a renderer bug runs as this process.
            # `--disable-dev-shm-usage` is the container fix that is actually
            # about containers: /dev/shm defaults to 64 MB and Chromium wants
            # more.
            _browser = await _playwright.chromium.launch(
                args=[
                    "--disable-dev-shm-usage",
                    # Headless Chromium treats its own window as occluded and
                    # throttles `requestAnimationFrame` down to nothing. A
                    # poster does not care; a game playtested under that looks
                    # exactly like a game whose loop has died. Harmless to the
                    # exports, which run with scripting off entirely.
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-background-timer-throttling",
                ]
            )
        except Exception as exc:  # noqa: BLE001 - any launch failure is the same to a caller
            raise RasterUnavailable(
                "Could not start the renderer. Download the file instead."
            ) from exc
        return _browser


async def shutdown() -> None:
    """Close the browser with the app, so a reload does not leave one behind."""
    global _browser, _playwright
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None


async def to_pdf(html: str, *, width: int, height: int) -> bytes:
    """A deck as a PDF, one slide to a page.

    The document already carries the print rules that do this — a page the size
    of a slide and a break after each one — so the browser only has to be asked
    politely. `print_background` because a deck without its colours is not the
    deck.
    """
    browser = await _ensure_browser()
    context = await browser.new_context(
        viewport={"width": max(width, 1), "height": max(height, 1)},
        java_script_enabled=False,
    )
    page = await context.new_page()
    try:
        await page.set_content(html, wait_until="load", timeout=LOAD_TIMEOUT_MS)
        await page.wait_for_timeout(FONT_SETTLE_MS)
        return await page.pdf(
            width=f"{width}px",
            height=f"{height}px",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            prefer_css_page_size=True,
        )
    finally:
        await context.close()


async def to_png(html: str, *, width: int, height: int, scale: int = 2) -> bytes:
    """The poster as a picture, at its own size.

    Twice the size by default: a poster is looked at closely and shared into
    places that resize it, and a crisp file survives both.
    """
    browser = await _ensure_browser()
    # Its own context, discarded with the page. Two exports never share a
    # cookie jar, a cache or anything a document could leave behind for the
    # next one.
    context = await browser.new_context(
        viewport={"width": max(width, 1), "height": max(height, 1)},
        device_scale_factor=scale,
        java_script_enabled=False,
    )
    page = await context.new_page()
    try:
        await page.set_content(html, wait_until="load", timeout=LOAD_TIMEOUT_MS)
        # Fonts first: a poster screenshotted before its display face arrives
        # is a poster in the fallback face, and it looks like a different one.
        # Waited for by the clock rather than by asking the document, because
        # scripting is off in here — a poster has none of its own, and a
        # renderer that runs none cannot be made to run any.
        await page.wait_for_timeout(FONT_SETTLE_MS)

        canvas = await page.query_selector(".canvas")
        if canvas is not None:
            # The canvas itself, not the window around it. A poster with the
            # page's ground showing down one side is not the poster.
            return await canvas.screenshot(type="png")
        return await page.screenshot(type="png")
    finally:
        await context.close()
