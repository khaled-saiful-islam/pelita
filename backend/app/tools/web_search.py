"""Web and image search, as tools.

Thin wrappers over `SearchProvider`. The provider knows how to talk to SerpAPI;
these say what the capability is called, what it looks like while it runs, and
how a model would describe wanting it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.providers.base import ToolResult
from app.tools.base import Tool, ToolPresentation, ToolUnavailable, text_parameter
from app.tools.serpapi import SearchProvider, SearchUnavailable


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web for current information: news, prices, weather, recent "
        "events, or anything that may have changed since training."
    )
    parameters = text_parameter("query", "What to search the web for")
    presentation = ToolPresentation(
        running="Searching the web",
        done="Searched the web",
        noun="result",
        failed="Search unavailable",
    )

    def __init__(self, search: SearchProvider, *, limit: int = 5) -> None:
        self._search = search
        self._limit = limit

    async def run(self, **kwargs: Any) -> Sequence[ToolResult]:
        try:
            return await self._search.search(str(kwargs["query"]), limit=self._limit)
        except SearchUnavailable as exc:
            raise ToolUnavailable(str(exc)) from exc


class ImageSearchTool(Tool):
    name = "image_search"
    description = (
        "Find pictures of something, for when the user asks to be shown it "
        "rather than told about it."
    )
    parameters = text_parameter("query", "What to find pictures of")
    presentation = ToolPresentation(
        running="Looking for images", done="Found images", noun="image"
    )

    def __init__(self, search: SearchProvider, *, limit: int = 6) -> None:
        self._search = search
        self._limit = limit

    async def run(self, **kwargs: Any) -> Sequence[ToolResult]:
        try:
            return await self._search.search_images(str(kwargs["query"]), limit=self._limit)
        except SearchUnavailable as exc:
            raise ToolUnavailable(str(exc)) from exc
