"""Web search via SerpAPI.

Returns `ToolResult`s for a context contributor to turn into prompt text. This
module knows nothing about prompts, and the contributor knows nothing about
SerpAPI — which is what lets either be replaced alone.
"""

from __future__ import annotations

import logging
from html import unescape
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.providers.base import ToolResult

logger = logging.getLogger(__name__)

SNIPPET_MAX_LENGTH = 400


class SearchProvider(Protocol):
    """Swap in Brave, Tavily or an internal index by implementing this."""

    name: str

    async def search(self, query: str, *, limit: int) -> list[ToolResult]: ...
    async def search_images(self, query: str, *, limit: int) -> list[ToolResult]: ...


class SearchUnavailable(RuntimeError):
    """Search failed in a way the user should be told about, without detail."""


class SerpApiSearch(SearchProvider):
    name = "web_search"

    def __init__(
        self, *, api_key: str, base_url: str = "https://serpapi.com/search", timeout: float = 20.0
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout

    def _prepare(self, query: str) -> str:
        query = query.strip()
        if not query:
            return ""
        if not self._api_key:
            raise SearchUnavailable("Web search is not configured. Set SERPAPI_KEY in .env.")
        return query

    async def search(self, query: str, *, limit: int = 5) -> list[ToolResult]:
        query = self._prepare(query)
        if not query:
            return []

        payload = await self._get(
            {"q": query, "engine": "google", "num": str(max(limit, 1))}
        )
        return parse_results(payload, limit=limit)

    async def _get(self, params: dict[str, str]) -> dict:
        """One request path, so both engines fail the same readable way."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    self._base_url, params={**params, "api_key": self._api_key}
                )
        except httpx.TimeoutException as exc:
            raise SearchUnavailable("The search provider timed out.") from exc
        except httpx.HTTPError as exc:
            logger.warning("search transport error: %s", exc)
            raise SearchUnavailable("Could not reach the search provider.") from exc

        if response.status_code == 401:
            raise SearchUnavailable("The search provider rejected the API key.")
        if response.status_code == 429:
            raise SearchUnavailable("Search quota exhausted.")
        if response.status_code >= 400:
            logger.warning("search returned %s: %s", response.status_code, response.text[:200])
            raise SearchUnavailable("The search provider returned an error.")

        return response.json()

    async def search_images(self, query: str, *, limit: int = 6) -> list[ToolResult]:
        """Image results for a query.

        A separate engine rather than a flag on `search`, because the response
        shape is different and conflating them would make both parsers guess.
        """
        query = self._prepare(query)
        if not query:
            return []
        payload = await self._get(
            {"q": query, "engine": "google_images", "num": str(max(limit, 1))}
        )
        return parse_image_results(payload, limit=limit)


# Stock libraries serve watermarked previews to non-subscribers. The picture is
# technically a match and visually useless, so they are skipped rather than
# shown with a diagonal logo across the middle.
WATERMARKED_HOSTS = frozenset(
    {
        "shutterstock.com",
        "alamy.com",
        "dreamstime.com",
        "istockphoto.com",
        "gettyimages.com",
        "gettyimages.co.uk",
        "123rf.com",
        "depositphotos.com",
        "stock.adobe.com",
        "vectorstock.com",
        "canstockphoto.com",
        "agefotostock.com",
        "bigstockphoto.com",
        "photostock.com",
        "shutterstock.co",
        "imago-images.com",
        "picfair.com",
    }
)

# Below this, a result is an icon, an avatar or a tracking pixel rather than a
# picture of the thing that was asked about.
MIN_IMAGE_EDGE = 200


def _is_watermarked(page_url: str, source: str) -> bool:
    host = urlparse(page_url).hostname or ""
    host = host.removeprefix("www.").lower()
    if any(host == blocked or host.endswith(f".{blocked}") for blocked in WATERMARKED_HOSTS):
        return True
    # Some results carry the library name only in the source label.
    lowered = source.lower()
    return any(blocked.split(".")[0] in lowered for blocked in WATERMARKED_HOSTS)


def _too_small(item: dict) -> bool:
    """Drop tiny images, but never drop one whose size is simply unreported."""
    width, height = item.get("original_width"), item.get("original_height")
    if not isinstance(width, int) or not isinstance(height, int):
        return False
    return width < MIN_IMAGE_EDGE or height < MIN_IMAGE_EDGE


def parse_image_results(payload: dict, *, limit: int) -> list[ToolResult]:
    """Pull image results out of a SerpAPI google_images response.

    `url` is set to the page the image appears on rather than the image file.
    A picture with no context is not a source someone can check.
    """
    found = payload.get("images_results") or []
    results: list[ToolResult] = []

    for item in found:
        thumbnail = (item.get("thumbnail") or "").strip()
        original = (item.get("original") or "").strip()
        if not thumbnail and not original:
            continue

        # A data: thumbnail is fine to render but must not be treated as a link.
        page = (item.get("link") or "").strip()
        if not _is_http(page):
            page = original if _is_http(original) else ""
        if not page:
            continue

        source = (item.get("source") or "").strip()[:120]
        if _is_watermarked(page, source) or _too_small(item):
            continue

        # Ranked after filtering, so the numbering matches what is shown rather
        # than leaving gaps where a stock photo was dropped.
        results.append(
            ToolResult(
                tool="image_search",
                title=_clean_text(item.get("title") or "Image")[:300],
                url=page,
                snippet=source,
                rank=len(results) + 1,
                thumbnail_url=thumbnail if _renderable(thumbnail) else original,
                image_url=original if _is_http(original) else "",
            )
        )
        if len(results) >= limit:
            break

    return results


def _clean_text(raw: str) -> str:
    """Decode HTML entities and collapse whitespace.

    Search snippets arrive as HTML fragments, so `&nbsp;` and `&amp;` reach the
    UI verbatim unless they are decoded — and they are rendered as text, not
    HTML, so nothing downstream will do it.
    """
    return " ".join(unescape(raw).split())


def _is_http(url: str) -> bool:
    return url.startswith("https://") or url.startswith("http://")


def _renderable(url: str) -> bool:
    """A thumbnail the browser can show: an http(s) URL or an inline data URI."""
    return _is_http(url) or url.startswith("data:image/")


def parse_results(payload: dict, *, limit: int) -> list[ToolResult]:
    """Pull the organic results out of a SerpAPI response.

    Tolerant on purpose: a missing field skips one result rather than failing
    the search, because a partial set of sources is more useful than none.
    """
    organic = payload.get("organic_results") or []
    results: list[ToolResult] = []

    for rank, item in enumerate(organic[:limit], start=1):
        title = _clean_text(item.get("title") or "")
        url = (item.get("link") or "").strip()
        if not title or not url:
            continue
        snippet = _clean_text(item.get("snippet") or "")[:SNIPPET_MAX_LENGTH]
        results.append(
            ToolResult(tool="web_search", title=title, url=url, snippet=snippet, rank=rank)
        )

    return results
