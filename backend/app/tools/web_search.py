"""Web and image search, as tools.

Thin wrappers over `SearchProvider`. The provider knows how to talk to SerpAPI;
these say what the capability is called, what it looks like while it runs, and
how a model would describe wanting it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any
from urllib.parse import urlparse

from app.providers.base import ToolResult
from app.tools.base import (
    Progress,
    Results,
    StreamingTool,
    Tool,
    ToolPresentation,
    ToolUnavailable,
    ToolUpdate,
    text_parameter,
)
from app.tools.page_reader import PageReader
from app.tools.serpapi import RECENCY, SearchProvider, SearchUnavailable


class WebSearchTool(StreamingTool):
    name = "web_search"
    # Read by the turn, so the search control governs search and nothing else.
    searches = True
    # Written for a model that believes it is still the year its training
    # ended. The query behind the answer that prompted this carried a year
    # from memory, and got a page of results about that year in general.
    description = (
        "Search the web, and read the top pages it finds. Use it for anything "
        "that may have changed since your training -- who currently holds a title "
        "or an office, prices, scores, releases, schedules, news, weather -- and "
        "to check any fact you are unsure of or that the person disputes. Write "
        "the query the way a person types into Google: a few specific words. "
        "Never add a year from memory: your sense of the current year is out of "
        "date, and today's date is given to you. Set recency for news or anything "
        "from the last days or weeks. If the results do not answer the question, "
        "or disagree, search again with a different query."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search the web for"},
            "recency": {
                "type": "string",
                "enum": list(RECENCY),
                "description": "Only results from the last day, week, month or year. "
                "Leave it out unless the question is about something recent.",
            },
        },
        "required": ["query"],
    }
    presentation = ToolPresentation(
        running="Searching the web",
        done="Searched the web",
        noun="result",
        failed="Search unavailable",
    )

    def __init__(
        self,
        search: SearchProvider,
        *,
        limit: int = 5,
        reader: PageReader | None = None,
        pages: int = 3,
    ) -> None:
        self._search = search
        self._limit = limit
        self._reader = reader
        self._pages = pages

    async def stream(self, **kwargs: Any) -> AsyncIterator[ToolUpdate]:
        query = str(kwargs.get("query") or "")
        recency = kwargs.get("recency")
        try:
            found = await self._search.search(
                query, limit=self._limit, recency=recency if recency in RECENCY else None
            )
        except SearchUnavailable as exc:
            raise ToolUnavailable(str(exc)) from exc

        if self._reader is not None and self._pages > 0:
            reading = PageReader.pick(found, self._pages)
            if reading:
                yield Progress(
                    label=f"Reading {len(reading)} page{'s' if len(reading) > 1 else ''}",
                    detail=", ".join(_hosts(reading)),
                )
                found = await self._reader.enrich(found, query=query, limit=self._pages)
        yield Results(items=tuple(found))


def _hosts(results: Sequence[ToolResult]) -> list[str]:
    """The sites being read, for the chip, as a person would name them."""
    hosts: list[str] = []
    for result in results:
        host = (urlparse(result.url).hostname or "").removeprefix("www.")
        if host and host not in hosts:
            hosts.append(host)
    return hosts


class ImageSearchTool(Tool):
    name = "image_search"
    searches = True
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
