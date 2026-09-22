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
            _browser = await _playwright.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage"]
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


async def to_png(html: str, *, width: int, height: int, scale: int = 2) -> bytes:
    """The poster as a picture, at its own size.

    Twice the size by default: a poster is looked at closely and shared into
    places that resize it, and a crisp file survives both.
    """
    browser = await _ensure_browser()
    page = await browser.new_page(
        viewport={"width": max(width, 1), "height": max(height, 1)},
        device_scale_factor=scale,
    )
    try:
        await page.set_content(html, wait_until="load", timeout=LOAD_TIMEOUT_MS)
        # Fonts first: a poster screenshotted before its display face arrives
        # is a poster in the fallback face, and it looks like a different one.
        try:
            await page.evaluate("document.fonts && document.fonts.ready")
        except Exception:  # noqa: BLE001 - an old engine without the API is fine
            logger.debug("no font loading API; exporting anyway")
        await page.wait_for_timeout(FONT_SETTLE_MS)

        canvas = await page.query_selector(".canvas")
        if canvas is not None:
            # The canvas itself, not the window around it. A poster with the
            # page's ground showing down one side is not the poster.
            return await canvas.screenshot(type="png")
        return await page.screenshot(type="png")
    finally:
        await page.close()
