"""Web search via SerpAPI.

Returns `ToolResult`s for a context contributor to turn into prompt text. This
module knows nothing about prompts, and the contributor knows nothing about
SerpAPI — which is what lets either be replaced alone.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.providers.base import ToolResult

logger = logging.getLogger(__name__)

SNIPPET_MAX_LENGTH = 400


class SearchProvider(Protocol):
    """Swap in Brave, Tavily or an internal index by implementing this."""

    name: str

    async def search(self, query: str, *, limit: int) -> list[ToolResult]: ...


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

    async def search(self, query: str, *, limit: int = 5) -> list[ToolResult]:
        query = query.strip()
        if not query:
            return []
        if not self._api_key:
            raise SearchUnavailable("Web search is not configured. Set SERPAPI_KEY in .env.")

        params = {
            "q": query,
            "api_key": self._api_key,
            "engine": "google",
            "num": str(max(limit, 1)),
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(self._base_url, params=params)
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

        return parse_results(response.json(), limit=limit)


def parse_results(payload: dict, *, limit: int) -> list[ToolResult]:
    """Pull the organic results out of a SerpAPI response.

    Tolerant on purpose: a missing field skips one result rather than failing
    the search, because a partial set of sources is more useful than none.
    """
    organic = payload.get("organic_results") or []
    results: list[ToolResult] = []

    for rank, item in enumerate(organic[:limit], start=1):
        title = (item.get("title") or "").strip()
        url = (item.get("link") or "").strip()
        if not title or not url:
            continue
        snippet = (item.get("snippet") or "").strip()[:SNIPPET_MAX_LENGTH]
        results.append(
            ToolResult(tool="web_search", title=title, url=url, snippet=snippet, rank=rank)
        )

    return results
