"""The tool-calling loop: the model choosing, and the turn coping when it can't."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from app.providers.base import (
    ChatRequest,
    FinishReason,
    ProviderInfo,
    Role,
    StreamEvent,
    TokenEvent,
    ToolCall,
    ToolCallsEvent,
    Usage,
    UsageSource,
)
from app.providers.openai_compatible import _absorb_call_fragment, _assemble_calls, _PartialCall
from app.services.events import DeltaEvent, SourcesEvent, ToolEvent
from app.tools.base import Tool, ToolPresentation, first_argument, text_parameter, tool_schema
from tests.test_chat_service import FakeProvider, build_service, collect


class LookupTool(Tool):
    name = "lookup"
    description = "Look something up."
    parameters = text_parameter("query", "What to look up")
    presentation = ToolPresentation(running="Looking up", done="Looked up", noun="hit")
    # This file is about what the search control does, so its stand-in tool is
    # one that searches. A tool that does not is covered below.
    searches = True

    def __init__(self, *, results_per_call: int = 2) -> None:
        self.calls: list[str] = []
        self._per_call = results_per_call

    async def run(self, **kwargs: Any) -> Sequence[Any]:
        from app.providers.base import ToolResult

        query = kwargs.get("query", "")
        self.calls.append(query)
        return [
            ToolResult(
                tool=self.name,
                title=f"{query} result {index}",
                url=f"https://example.test/{len(self.calls)}/{index}",
                snippet=f"about {query}",
                rank=index,
            )
            for index in range(1, self._per_call + 1)
        ]


class ScriptedProvider:
    """Plays a fixed script of streamed turns, so a loop can be asserted on.

    Each entry is either a list of `ToolCall` (the model asking) or a string
    (the model answering).
    """

    def __init__(self, script: list[Any], *, usage: int = 10) -> None:
        self._script = list(script)
        self._usage = usage
        self.requests: list[ChatRequest] = []
        self.info = ProviderInfo(name="scripted", model="scripted-model", base_url="")

    async def stream_chat(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        step = self._script.pop(0) if self._script else "done"
        if isinstance(step, list):
            yield ToolCallsEvent(calls=tuple(step))
        else:
            yield TokenEvent(text=step)
        yield _usage_event(self._usage)

    async def complete(self, req: ChatRequest) -> Any:  # pragma: no cover - unused
        raise NotImplementedError


def _usage_event(tokens: int):
    from app.providers.base import UsageEvent

    return UsageEvent(
        usage=Usage(
            prompt_tokens=tokens, completion_tokens=tokens, source=UsageSource.PROVIDER
        )
    )


def call(name: str, query: str, *, id: str = "c1") -> ToolCall:
    return ToolCall(id=id, name=name, arguments=json.dumps({"query": query}))


async def run(service, db_user, content="anything", mode="auto"):
    return await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content=content,
        search_mode=mode,
    )


def scripted(session, registry, script, tool):
    return build_service(
        session,
        ScriptedProvider(script),
        registry,
        tools={tool.name: tool},
        tool_calling=True,
    )


# --- schema -------------------------------------------------------------


def test_a_tool_describes_itself_in_the_wire_format() -> None:
    schema = tool_schema(LookupTool())
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "lookup"
    assert schema["function"]["description"]
    assert schema["function"]["parameters"]["properties"]["query"]


def test_the_declared_parameter_is_preferred() -> None:
    assert first_argument(LookupTool(), {"query": "nasi lemak"}) == "nasi lemak"


def test_a_plausible_wrong_key_still_runs() -> None:
    """Models return `q` for `query` often enough that failing on it would be
    choosing pedantry over an answer."""
    assert first_argument(LookupTool(), {"q": "nasi lemak"}) == "nasi lemak"


def test_no_usable_argument_is_reported_as_empty() -> None:
    assert first_argument(LookupTool(), {"query": "   "}) == ""
    assert first_argument(LookupTool(), {}) == ""


# --- assembling streamed calls -----------------------------------------


def test_argument_fragments_are_joined_in_arrival_order() -> None:
    """Arguments arrive a few characters at a time and are useless until whole."""
    calls: dict[int, _PartialCall] = {}
    _absorb_call_fragment(
        calls, {"index": 0, "id": "c1", "function": {"name": "lookup", "arguments": '{"qu'}}
    )
    _absorb_call_fragment(calls, {"index": 0, "function": {"arguments": 'ery": "kl"}'}})

    assembled = _assemble_calls(calls)
    assert assembled == (ToolCall(id="c1", name="lookup", arguments='{"query": "kl"}'),)


def test_a_missing_index_does_not_start_a_new_call() -> None:
    """Some providers omit `index` for a single call; one call per chunk would
    produce a dozen empty ones."""
    calls: dict[int, _PartialCall] = {}
    _absorb_call_fragment(calls, {"id": "c1", "function": {"name": "lookup", "arguments": "{}"}})
    _absorb_call_fragment(calls, {"function": {"arguments": ""}})
    assert len(_assemble_calls(calls)) == 1


def test_two_calls_keep_their_own_arguments() -> None:
    calls: dict[int, _PartialCall] = {}
    _absorb_call_fragment(
        calls, {"index": 0, "id": "a", "function": {"name": "lookup", "arguments": '{"query":"x"}'}}
    )
    _absorb_call_fragment(
        calls, {"index": 1, "id": "b", "function": {"name": "lookup", "arguments": '{"query":"y"}'}}
    )
    assembled = _assemble_calls(calls)
    assert [c.id for c in assembled] == ["a", "b"]
    assert assembled[1].arguments == '{"query":"y"}'


def test_a_fragment_with_no_name_is_dropped() -> None:
    """It cannot be dispatched, and an empty name would be reported as an
    unknown tool rather than as the provider bug it is."""
    calls: dict[int, _PartialCall] = {}
    _absorb_call_fragment(calls, {"index": 0, "function": {"arguments": "{}"}})
    assert _assemble_calls(calls) == ()


def test_calls_come_back_in_index_order() -> None:
    calls = {
        1: _PartialCall(id="b", name="lookup", arguments="{}"),
        0: _PartialCall(id="a", name="lookup", arguments="{}"),
    }
    assert [c.id for c in _assemble_calls(calls)] == ["a", "b"]


# --- the loop -----------------------------------------------------------


async def test_the_model_chooses_and_the_tool_runs(session, db_user, registry) -> None:
    tool = LookupTool()
    service = scripted(session, registry, [[call("lookup", "nasi lemak")], "Here it is."], tool)

    events = await run(service, db_user, content="tell me about nasi lemak")

    assert tool.calls == ["nasi lemak"]
    assert "Here it is." in "".join(e.text for e in events if isinstance(e, DeltaEvent))


async def test_the_chip_shows_what_the_model_looked_up(session, db_user, registry) -> None:
    """More use than a regex's reason: it is the actual query."""
    service = scripted(
        session, registry, [[call("lookup", "nasi lemak history")], "ok"], LookupTool()
    )
    events = await run(service, db_user)

    running = next(e for e in events if isinstance(e, ToolEvent) and e.status == "running")
    assert running.detail == "nasi lemak history"


async def test_tools_are_offered_with_their_schema(session, db_user, registry) -> None:
    provider = ScriptedProvider(["no tools needed"])
    service = build_service(
        session, provider, registry, tools={"lookup": LookupTool()}, tool_calling=True
    )
    await run(service, db_user)

    offered = provider.requests[0].tools
    assert [t["function"]["name"] for t in offered] == ["lookup"]
    assert provider.requests[0].tool_choice == "auto"


async def test_search_mode_always_requires_a_tool(session, db_user, registry) -> None:
    """"Always" has to mean always, not "consider it"."""
    provider = ScriptedProvider([[call("lookup", "x")], "ok"])
    service = build_service(
        session, provider, registry, tools={"lookup": LookupTool()}, tool_calling=True
    )
    await run(service, db_user, mode="always")

    assert provider.requests[0].tool_choice == "required"
    # Forced once only, or the model calls forever instead of answering.
    assert provider.requests[1].tool_choice == "auto"


async def test_search_mode_off_offers_no_searching(session, db_user, registry) -> None:
    provider = ScriptedProvider(["ok"])
    tool = LookupTool()
    service = build_service(
        session, provider, registry, tools={"lookup": tool}, tool_calling=True
    )
    await run(service, db_user, mode="off")

    assert provider.requests[0].tools == ()
    assert tool.calls == []


async def test_search_off_leaves_everything_else_alone(session, db_user, registry) -> None:
    """Reported as "it is not working": asked for a slide deck with search off,
    the model typed the headings into the chat, because the turn returned
    before offering any tool at all and there was nothing to call.
    """
    from tests.test_tool_protocol import WeatherTool

    provider = ScriptedProvider([[call("weather", "KL")], "ok"])
    tool = WeatherTool()
    service = build_service(
        session, provider, registry, tools={"weather": tool}, tool_calling=True
    )
    await run(service, db_user, mode="off")

    assert [t["function"]["name"] for t in provider.requests[0].tools] == ["weather"]
    assert tool.calls


async def test_the_exchange_is_replayed_to_the_model(session, db_user, registry) -> None:
    """The model has to see what it asked for and what came back, or it asks
    again."""
    provider = ScriptedProvider([[call("lookup", "x")], "ok"])
    service = build_service(
        session, provider, registry, tools={"lookup": LookupTool()}, tool_calling=True
    )
    await run(service, db_user)

    second = provider.requests[1].messages
    assert second[-2].role is Role.ASSISTANT
    assert second[-2].tool_calls[0].name == "lookup"
    assert second[-1].role is Role.TOOL
    assert second[-1].tool_call_id == "c1"
    assert "about x" in second[-1].content


async def test_results_reach_the_model_as_a_tool_message_not_twice(
    session, db_user, registry
) -> None:
    """They are in the exchange already; the contributor would send them again."""
    provider = ScriptedProvider([[call("lookup", "x")], "ok"])
    service = build_service(
        session, provider, registry, tools={"lookup": LookupTool()}, tool_calling=True
    )
    await run(service, db_user)

    tool_messages = [m for m in provider.requests[1].messages if m.role is Role.TOOL]
    assert len(tool_messages) == 1
    systems = "\n".join(
        m.content for m in provider.requests[1].messages if m.role is Role.SYSTEM
    )
    assert "https://example.test" not in systems


async def test_two_rounds_of_tools_renumber_their_citations(
    session, db_user, registry
) -> None:
    """Both searches come back numbered from 1, and a duplicate [2] would mean
    two different pages in one answer."""
    provider = ScriptedProvider(
        [[call("lookup", "first")], [call("lookup", "second", id="c2")], "done"]
    )
    service = build_service(
        session, provider, registry, tools={"lookup": LookupTool()}, tool_calling=True
    )
    events = await run(service, db_user)

    ranks = [s.rank for e in events if isinstance(e, SourcesEvent) for s in e.sources]
    assert ranks == [1, 2, 3, 4]


async def test_usage_is_summed_across_the_loop(session, db_user, registry) -> None:
    """A turn that called a tool paid for two model calls. Reporting the last
    one prices it at half."""
    provider = ScriptedProvider([[call("lookup", "x")], "ok"], usage=10)
    service = build_service(
        session, provider, registry, tools={"lookup": LookupTool()}, tool_calling=True
    )
    events = await run(service, db_user)

    accounting = next(e.accounting for e in events if hasattr(e, "accounting"))
    assert accounting.prompt_tokens == 20
    assert accounting.completion_tokens == 20


async def test_the_loop_stops_at_its_cap(session, db_user, registry) -> None:
    """Otherwise a model that always calls a tool never answers."""
    tool = LookupTool()
    provider = ScriptedProvider([[call("lookup", f"q{i}", id=f"c{i}")] for i in range(10)])
    service = build_service(
        session, provider, registry, tools={"lookup": tool}, tool_calling=True
    )
    await run(service, db_user)

    # Three rounds of tools, then a pass with none offered so it has to reply.
    assert len(tool.calls) == 3
    assert provider.requests[-1].tools == ()


async def test_an_unknown_tool_is_answered_not_ignored(session, db_user, registry) -> None:
    """An unanswered tool_call id is a protocol error on the next request, so
    the refusal has to go into the exchange."""
    provider = ScriptedProvider([[call("teleport", "mars")], "sorry"])
    service = build_service(
        session, provider, registry, tools={"lookup": LookupTool()}, tool_calling=True
    )
    events = await run(service, db_user)

    failed = next(e for e in events if isinstance(e, ToolEvent) and e.status == "failed")
    assert failed.tool == "teleport"
    tool_message = [m for m in provider.requests[1].messages if m.role is Role.TOOL][0]
    assert "no tool named teleport" in tool_message.content.lower()


async def test_malformed_arguments_are_answered_so_the_model_can_retry(
    session, db_user, registry
) -> None:
    provider = ScriptedProvider(
        [[ToolCall(id="c1", name="lookup", arguments="{not json")], "recovered"]
    )
    tool = LookupTool()
    service = build_service(
        session, provider, registry, tools={"lookup": tool}, tool_calling=True
    )
    events = await run(service, db_user)

    assert tool.calls == []
    assert any(isinstance(e, ToolEvent) and e.status == "failed" for e in events)
    tool_message = [m for m in provider.requests[1].messages if m.role is Role.TOOL][0]
    assert "valid JSON" in tool_message.content


async def test_an_argumentless_call_is_answered(session, db_user, registry) -> None:
    provider = ScriptedProvider([[ToolCall(id="c1", name="lookup", arguments="{}")], "ok"])
    tool = LookupTool()
    service = build_service(
        session, provider, registry, tools={"lookup": tool}, tool_calling=True
    )
    await run(service, db_user)

    assert tool.calls == []
    tool_message = [m for m in provider.requests[1].messages if m.role is Role.TOOL][0]
    # Named, not just refused: the model can only fix the call if it is told
    # which argument was missing.
    assert "query" in tool_message.content


async def test_two_calls_in_one_round_both_run(session, db_user, registry) -> None:
    tool = LookupTool()
    provider = ScriptedProvider(
        [[call("lookup", "first", id="a"), call("lookup", "second", id="b")], "both done"]
    )
    service = build_service(
        session, provider, registry, tools={"lookup": tool}, tool_calling=True
    )
    await run(service, db_user)

    assert tool.calls == ["first", "second"]
    answered = [
        m.tool_call_id for m in provider.requests[1].messages if m.role is Role.TOOL
    ]
    assert answered == ["a", "b"]


# --- falling back ------------------------------------------------------


async def test_a_provider_that_cannot_do_tools_still_searches(
    session, db_user, registry
) -> None:
    """A local build with no function calling should lose the model's choice,
    not the tool."""
    tool = LookupTool()
    provider = FakeProvider(["answered"], supports_tools=False)
    service = build_service(
        session, provider, registry, tools={"web_search": tool}, tool_calling=True
    )
    await run(service, db_user, content="what is the weather in KL", mode="always")

    assert tool.calls == ["what is the weather in KL"]
    assert provider.received is not None
    assert provider.received.tools == ()


async def test_tool_calling_disabled_uses_the_pattern_path(
    session, db_user, registry
) -> None:
    tool = LookupTool()
    provider = FakeProvider(["answered"])
    service = build_service(
        session, provider, registry, tools={"web_search": tool}, tool_calling=False
    )
    await run(service, db_user, content="what is the weather in KL", mode="always")

    assert tool.calls == ["what is the weather in KL"]


async def test_no_tools_at_all_is_a_single_pass(session, db_user, registry) -> None:
    provider = ScriptedProvider(["just an answer"])
    service = build_service(session, provider, registry, tools={}, tool_calling=True)
    events = await run(service, db_user)

    assert len(provider.requests) == 1
    assert "just an answer" in "".join(
        e.text for e in events if isinstance(e, DeltaEvent)
    )


@pytest.mark.parametrize("finish", [FinishReason.TOOL_CALLS])
def test_tool_calls_is_a_finish_reason(finish) -> None:
    """So a turn that ended by asking for a tool is distinguishable from one
    that ended by answering."""
    assert str(finish) == "tool_calls"
