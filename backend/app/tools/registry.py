"""The tools available to a turn.

Adding a calculator, a database lookup or a retrieval step is one file
implementing `Tool` and one entry here. Nothing in the chat service names a
tool, so nothing there changes.

A tool whose dependency is missing is not registered at all. That is why an
install with no search key and no artifact model still runs: the model is
offered a shorter list, rather than a capability that fails every time it is
used.
"""

from __future__ import annotations

from app.artifacts.registry import build_kinds
from app.core.config import Settings, get_settings
from app.tools.artifact import CreateArtifactTool, EditArtifactTool
from app.tools.base import Tool
from app.tools.page_reader import PageReader
from app.tools.serpapi import SerpApiSearch
from app.tools.web_search import ImageSearchTool, WebSearchTool


def build_tools(settings: Settings | None = None) -> dict[str, Tool]:
    """Keyed by name, so a selection step can look one up without a scan."""
    settings = settings or get_settings()
    tools: list[Tool] = []

    if settings.search_enabled:
        # No key, so the tools that need one simply do not exist. The UI reads
        # this through /api/config and disables the control rather than
        # offering something that always fails.
        search = SerpApiSearch(
            api_key=settings.serpapi_key,
            base_url=settings.serpapi_base_url,
            country=settings.search_country,
        )
        tools += [
            WebSearchTool(
                search,
                limit=settings.search_max_results,
                reader=PageReader(timeout=settings.search_read_timeout_seconds),
                pages=settings.search_read_pages,
            ),
            ImageSearchTool(search, limit=settings.image_max_results),
        ]

    # Same rule, one layer up: no artifact model means no kinds, and no kinds
    # means the tool is never offered rather than offered and always failing.
    kinds = build_kinds(settings)
    if kinds:
        tools.append(CreateArtifactTool(kinds))
        # Offered only on a turn that has one open. `_tools_to_offer` decides
        # that, so the model is never shown a way to change nothing.
        tools.append(EditArtifactTool(kinds))

    return {tool.name: tool for tool in tools}
