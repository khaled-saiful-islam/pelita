"""The tools available to a turn.

Adding a calculator, a database lookup or a retrieval step is one file
implementing `Tool` and one entry here. Nothing in the chat service names a
tool, so nothing there changes.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.tools.base import Tool
from app.tools.serpapi import SerpApiSearch
from app.tools.web_search import ImageSearchTool, WebSearchTool


def build_tools(settings: Settings | None = None) -> dict[str, Tool]:
    """Keyed by name, so a selection step can look one up without a scan."""
    settings = settings or get_settings()
    if not settings.search_enabled:
        # No key, so the tools that need one simply do not exist. The UI reads
        # this through /api/config and disables the control rather than
        # offering something that always fails.
        return {}

    search = SerpApiSearch(
        api_key=settings.serpapi_key, base_url=settings.serpapi_base_url
    )
    tools: list[Tool] = [
        WebSearchTool(search, limit=settings.search_max_results),
        ImageSearchTool(search, limit=settings.image_max_results),
    ]
    return {tool.name: tool for tool in tools}
