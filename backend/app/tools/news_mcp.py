"""News headlines over the Model Context Protocol.

Uses the official Python MCP SDK as a client, spawning any MCP server that
exposes a headlines tool. The default is `moltrus/google-news-mcp`, pinned by
commit and installed into its own virtualenv in the API image.

That server imports `mcp.server.fastmcp.FastMCP`, which exists only in `mcp<2`,
while this client runs `mcp` 2.x. The two talk fine — the protocol negotiates
versions — which is why the server gets an isolated environment rather than
holding the whole backend back a major version.

Every failure here is contained. If the strip cannot load, it is hidden. News is
a nice-to-have decoration on the new-chat screen and must never be able to break
chat.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

SNIPPET_MAX_LENGTH = 220


@dataclass(frozen=True, slots=True)
class NewsItem:
    title: str
    url: str
    source: str
    published_at: str | None
    snippet: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "snippet": self.snippet,
        }


class NewsUnavailable(RuntimeError):
    """The MCP server could not be reached or did not answer usefully."""


@dataclass(frozen=True, slots=True)
class NewsMcpConfig:
    command: str
    args: tuple[str, ...]
    tool: str
    language: str
    country: str
    timeout: float
    max_items: int
    # When set, headlines are searched for this instead of taken from the
    # general front page. Used to follow what the user actually talks about.
    query: str = ""

    @property
    def effective_tool(self) -> str:
        return self.search_tool if self.query else self.tool

    # The server exposes both; which one to call depends on whether we have a
    # topic worth searching for.
    search_tool: str = "get_search_feed"

    def tool_arguments(self) -> dict[str, str]:
        arguments = {"language": self.language, "country": self.country}
        if self.query:
            arguments["query"] = self.query
        return arguments


async def fetch_headlines(config: NewsMcpConfig) -> list[NewsItem]:
    """Spawn the server, call the tool, and parse what comes back."""
    params = StdioServerParameters(command=config.command, args=list(config.args), env=None)

    try:
        with anyio.fail_after(config.timeout):
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    config.effective_tool, config.tool_arguments()
                )
    except TimeoutError as exc:
        raise NewsUnavailable(f"MCP server timed out after {config.timeout}s") from exc
    except Exception as exc:  # noqa: BLE001 - any failure means "hide the strip"
        raise NewsUnavailable(f"MCP server unavailable: {type(exc).__name__}: {exc}") from exc

    text = _first_text(result)
    if not text:
        raise NewsUnavailable("MCP server returned no content")

    return parse_feed(text, max_items=config.max_items)


def _first_text(result: object) -> str | None:
    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            return text
    return None


def parse_feed(raw: str, *, max_items: int) -> list[NewsItem]:
    """Turn the tool's payload into items.

    Written against what `google-news-mcp` actually returns — a JSON object with
    an `entries` list — but tolerant of shape differences, because the point of
    `MCP_NEWS_COMMAND` is that someone can point this at a different server.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NewsUnavailable("MCP server returned content that was not JSON") from exc

    entries = _entries_from(payload)
    items: list[NewsItem] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = _clean(str(entry.get("title") or ""))
        url = str(entry.get("link") or entry.get("url") or "").strip()
        if not title or not url:
            continue

        items.append(
            NewsItem(
                title=title,
                url=url,
                source=_source_of(entry, title),
                published_at=_first_str(entry, "published", "published_at", "updated", "date"),
                snippet=_clean(
                    _first_str(entry, "summary", "description", "snippet") or ""
                )[:SNIPPET_MAX_LENGTH],
            )
        )
        if len(items) >= max_items * 2:
            # Over-fetch so the recency sort below has something to choose from.
            break

    if not items:
        raise NewsUnavailable("MCP server returned no usable headlines")

    # The search feed ranks by relevance, which puts month-old articles under a
    # heading that says "In the news". Freshest first is what the label promises.
    items.sort(key=_published_sort_key, reverse=True)
    return items[:max_items]


def _published_sort_key(item: NewsItem) -> float:
    """Epoch seconds, or 0 when the date is missing or unparseable.

    Undated items sort last rather than being dropped — a headline with no
    timestamp is still a headline.
    """
    if not item.published_at:
        return 0.0
    try:
        return parsedate_to_datetime(item.published_at).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(item.published_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _entries_from(payload: object) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("entries", "items", "articles", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _first_str(entry: dict, *keys: str) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _source_of(entry: dict, title: str) -> str:
    """Publisher name.

    Google News titles end in " - Publisher", which is the most reliable place
    to find it when the feed has no explicit field.
    """
    source = entry.get("source")
    if isinstance(source, dict):
        name = source.get("title") or source.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(source, str) and source.strip():
        return source.strip()

    if " - " in title:
        return title.rsplit(" - ", 1)[1].strip()
    return "News"


def _clean(text: str) -> str:
    """Strip tags and collapse whitespace.

    Feed summaries arrive as HTML fragments; the cards render as plain text.
    """
    out: list[str] = []
    depth = 0
    for char in text:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(char)
    # Entities too: stripping tags leaves "&nbsp;" and "&amp;" as visible text,
    # and these render as text rather than HTML downstream.
    return " ".join(unescape("".join(out)).split())
