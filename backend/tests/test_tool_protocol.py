"""The tool seam.

These tests exist to keep a promise honest: adding a capability should be one
file plus one registry line, and the chat service should never need to know
which tool it is running. If someone adds a branch on `tool.name` in the
service, one of these fails.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from app.core.config import Settings
from app.providers.base import ToolCall, ToolResult
from app.services.events import ImagesEvent, SourcesEvent, ToolEvent
from app.tools.base import Tool, ToolPresentation, ToolUnavailable, text_parameter
from app.tools.registry import build_tools
from tests.test_chat_service import FakeProvider, build_service, collect

# The seam has two paths to the same tool: the turn picking one from the
# question, and the model asking for it. Every claim below is asserted against
# both, because "the service never names a tool" has to hold on each.
PATHS = ["patterns", "model"]


def service_for(path, session, registry, tool, *, chunks=None, query="weather please"):
    """A service on one of the two paths, running the same tool either way.

    The registry key differs by necessity: the pattern path finds a tool by the
    slot it occupies, the model path by the name the tool gives itself. That the
    two disagree is exactly why dispatch re-keys on `tool.name`.
    """
    provider = FakeProvider(
        chunks or ["ok"],
        tool_calls=(
            [ToolCall(id="call_1", name=tool.name, arguments=json.dumps({"query": query}))]
            if path == "model"
            else None
        ),
    )
    return build_service(
        session,
        provider,
        registry,
        tools={"web_search": tool},
        tool_calling=path == "model",
    )


class WeatherTool(Tool):
    """A capability the codebase has never heard of, added from outside."""

    name = "weather"
    description = "Look up the current weather somewhere."
    parameters = text_parameter("query", "Where to look up the weather")
    presentation = ToolPresentation(
        running="Checking the weather", done="Checked the weather", noun="reading"
    )

    def __init__(self, *, fail: str | None = None) -> None:
        self._fail = fail
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> Sequence[ToolResult]:
        self.calls.append(kwargs)
        if self._fail:
            raise ToolUnavailable(self._fail)
        return [
            ToolResult(
                tool=self.name,
                title="Kuala Lumpur forecast",
                url="https://weather.test/kl",
                snippet="Mostly cloudy, 31C",
                rank=1,
            )
        ]


# --- the protocol -------------------------------------------------------


def test_the_shipped_tools_satisfy_the_protocol() -> None:
    tools = build_tools(Settings(_env_file=None, serpapi_key="k"))  # type: ignore[call-arg]
    assert set(tools) == {"web_search", "image_search"}
    assert all(isinstance(tool, Tool) for tool in tools.values())


def test_tools_that_need_a_key_do_not_exist_without_one() -> None:
    """The UI reads this through /api/config and disables the control, rather
    than offering a button that always fails."""
    assert build_tools(Settings(_env_file=None, serpapi_key="")) == {}  # type: ignore[call-arg]


def test_every_tool_describes_itself_well_enough_for_a_model_to_choose() -> None:
    """A tool-calling loop builds its schema from these, so they cannot be blank."""
    for tool in build_tools(Settings(_env_file=None, serpapi_key="k")).values():  # type: ignore[call-arg]
        assert tool.description.strip()
        assert tool.parameters.get("type") == "object"
        assert tool.parameters.get("required")
        assert tool.presentation.running and tool.presentation.done


# --- running an unknown tool -------------------------------------------


@pytest.mark.parametrize("path", PATHS)
async def test_a_tool_the_service_has_never_heard_of_runs_unchanged(
    session, db_user, registry, path
) -> None:
    """The point of the seam: no branch in chat_service names this tool."""
    question = "what is the current weather in KL?"
    weather = WeatherTool()
    service = service_for(path, session, registry, weather, query=question)

    events = await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content=question,
        search_mode="always",
    )

    assert weather.calls == [{"query": question}]
    labels = [e.label for e in events if isinstance(e, ToolEvent)]
    assert labels == ["Checking the weather", "Checked the weather"]


@pytest.mark.parametrize("path", PATHS)
async def test_its_results_become_sources(session, db_user, registry, path) -> None:
    service = service_for(path, session, registry, WeatherTool())
    events = await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="weather please",
        search_mode="always",
    )

    sources = next(e.sources for e in events if isinstance(e, SourcesEvent))
    assert sources[0].title == "Kuala Lumpur forecast"


@pytest.mark.parametrize("path", PATHS)
async def test_the_done_label_reports_the_tools_own_noun(
    session, db_user, registry, path
) -> None:
    """"1 reading in 0.0s", not "1 result" — the service does not name it."""
    service = service_for(path, session, registry, WeatherTool())
    events = await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="weather please",
        search_mode="always",
    )

    done = [e for e in events if isinstance(e, ToolEvent) and e.status == "done"][0]
    assert done.detail.startswith("1 reading in ")


@pytest.mark.parametrize("path", PATHS)
async def test_a_failing_tool_degrades_the_turn_without_ending_it(
    session, db_user, registry, path
) -> None:
    service = service_for(
        path,
        session,
        registry,
        WeatherTool(fail="station offline"),
        chunks=["answered anyway"],
    )
    events = await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="weather please",
        search_mode="always",
    )

    failed = [e for e in events if isinstance(e, ToolEvent) and e.status == "failed"]
    assert failed and "station offline" in failed[0].detail
    assert "answered anyway" in "".join(
        e.text for e in events if hasattr(e, "text")
    )


@pytest.mark.parametrize("path", PATHS)
async def test_image_results_are_recognised_by_shape_not_by_tool_name(
    session, db_user, registry, path
) -> None:
    """A tool returning results with thumbnails gets the image grid, whatever
    it is called."""

    class Pictures(WeatherTool):
        name = "pictures"

        async def run(self, **kwargs: Any) -> Sequence[ToolResult]:
            return [
                ToolResult(
                    tool="pictures",
                    title="A photo",
                    url="https://page.test",
                    snippet="",
                    rank=1,
                    thumbnail_url="https://thumb.test/1.jpg",
                )
            ]

    service = service_for(path, session, registry, Pictures())
    events = await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="anything",
        search_mode="always",
    )

    assert any(isinstance(e, ImagesEvent) for e in events)
    assert not any(isinstance(e, SourcesEvent) for e in events)


@pytest.mark.parametrize("mode", ["off", "auto"])
async def test_tools_do_not_run_when_the_turn_does_not_call_for_them(
    session, db_user, registry, mode
) -> None:
    weather = WeatherTool()
    service = build_service(
        session, FakeProvider(["ok"]), registry, tools={"web_search": weather}
    )
    await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        # No pattern fires, and the fake provider's classifier answers with its
        # chunks rather than YES, so auto declines too.
        content="write me a haiku about lanterns" if mode == "auto" else "anything",
        search_mode=mode,
    )
    assert weather.calls == []
