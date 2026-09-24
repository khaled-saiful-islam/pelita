"""What a tool is.

A tool takes named arguments, does something, and returns results. It also
carries what the UI should say while it runs and what a model needs to know to
choose it — so the chat service can run any tool without knowing which one it is.

That last property is the point. Today the turn decides which tools to run from
a query; when a model does the choosing instead, the same protocol serves, and
only the selection changes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.artifacts.base import Built
from app.providers.base import ToolResult


class ToolUnavailable(RuntimeError):
    """The tool could not run, with a message safe to show a user.

    Raised rather than returning empty, because "it failed" and "there were no
    results" deserve different words on screen.
    """


@dataclass(frozen=True, slots=True)
class ToolPresentation:
    """What the UI says about a tool while it works.

    Lives on the tool so the service never needs a branch per tool name.
    """

    running: str  # "Searching the web"
    done: str  # "Searched the web"
    noun: str  # "result" — pluralised by the caller
    # What to say when it could not run at all. A poster that failed to build
    # reporting "Search unavailable" is a tool's words in another tool's mouth.
    failed: str = "Could not finish"


@runtime_checkable
class Tool(Protocol):
    """Adding a tool is one file implementing this plus one registry line."""

    name: str
    # Written for a model to read when choosing. Kept on the tool so a future
    # tool-calling loop can build its own schema without a lookup table.
    description: str
    parameters: dict[str, Any]
    presentation: ToolPresentation

    async def run(self, **kwargs: Any) -> Sequence[ToolResult]: ...


@dataclass(frozen=True, slots=True)
class Progress:
    """Something a tool wants said while it is still working.

    A search is over before anyone reads the chip. Work measured in tens of
    seconds is not, and a tool that goes quiet for a minute is
    indistinguishable from one that has hung.
    """

    label: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Results:
    """What a tool found. The same shape whether it arrived all at once or
    in instalments, so nothing downstream needs to know which."""

    items: tuple[ToolResult, ...]


@dataclass(frozen=True, slots=True)
class Making:
    """A tool has begun making an artifact.

    Sent before the first step so the panel can open and say what is coming,
    rather than appearing fully formed a minute later.
    """

    kind: str
    title: str


@dataclass(frozen=True, slots=True)
class Drafting:
    """A piece of an artifact's source, as it is being written.

    Streamed so the panel can show the document arriving. The preview waits for
    the finished one — a half-written document renders as a broken one, and
    watching a layout thrash is worse than watching code arrive.
    """

    text: str


@dataclass(frozen=True, slots=True)
class Planned:
    """The pieces an artifact is going to have, named before they exist."""

    titles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Looks:
    """The palette and faces an artifact has chosen, while it is being made."""

    movement: str
    palette: tuple[str, ...]
    display_font: str
    body_font: str
    rationale: str = ""
    width: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True)
class Piece:
    """Part of an artifact, finished ahead of the rest.

    Sent so the panel can show slide one while slide seven is still being
    written. In order, whatever order they finished in: a deck that appears
    out of sequence is worse than one that appears slowly.
    """

    index: int
    total: int
    title: str
    html: str


@dataclass(frozen=True, slots=True)
class Made:
    """A finished artifact, handed back for the caller to store.

    The tool makes it; it does not save it. Storing needs the conversation, the
    message and a session, none of which a tool has any business holding.
    """

    kind: str
    title: str
    built: Built
    # Set when this replaces something that already exists, in which case it is
    # the next version of it rather than a new artifact.
    replaces: Any | None = None


ToolUpdate = Progress | Results | Making | Drafting | Planned | Looks | Piece | Made


@runtime_checkable
class SearchingTool(Protocol):
    """A tool that goes and looks something up on the web.

    Declared so the search control can govern searching and nothing else.
    Turning search off used to take every tool with it, including the ones
    that make things, because one early return covered them all.
    """

    searches: bool


@runtime_checkable
class ArtifactAwareTool(Protocol):
    """A tool that acts on whatever the person is currently looking at.

    Declared, not named: the service offers these only when there is an open
    artifact and hands it in, so "make it warmer" has a subject. A tool that
    does not declare this never learns an artifact exists.
    """

    wants_open_artifact: bool


@runtime_checkable
class ProgressiveTool(Protocol):
    """A tool with an interior worth narrating.

    Checked by shape, never by name — the same rule that decides an image
    result from its `thumbnail_url` rather than from which tool returned it.
    """

    async def stream(self, **kwargs: Any) -> AsyncIterator[ToolUpdate]: ...


class StreamingTool:
    """Implement `stream`; `run` follows from it.

    Here so a narrating tool is not obliged to write the same collection loop
    every time, and so it still satisfies `Tool` for every caller that only
    wants the results.
    """

    async def stream(self, **kwargs: Any) -> AsyncIterator[ToolUpdate]:  # pragma: no cover
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator

    async def run(self, **kwargs: Any) -> Sequence[ToolResult]:
        found: list[ToolResult] = []
        async for update in self.stream(**kwargs):
            if isinstance(update, Results):
                found.extend(update.items)
        return found


def tool_schema(tool: Tool) -> dict[str, Any]:
    """The OpenAI function-calling description of a tool.

    Built from the protocol's own fields, so a tool becomes model-callable by
    existing. There is no registry of schemas to keep in step.
    """
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def first_argument(tool: Tool, arguments: dict[str, Any]) -> str:
    """The value of the tool's first declared parameter, whatever it is called.

    Models sometimes return the right value under a plausible wrong key —
    `q` for `query` is the common one. Falling back to position means a
    near-miss runs instead of failing, and the tool's own schema is what
    defines "first".
    """
    declared = list((tool.parameters.get("properties") or {}).keys())
    for name in declared:
        if isinstance(arguments.get(name), str) and arguments[name].strip():
            return arguments[name].strip()
    for value in arguments.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def bind_arguments(tool: Tool, arguments: dict[str, Any]) -> dict[str, Any]:
    """What the model sent, reduced to what the tool declared.

    Undeclared keys are dropped rather than forwarded: a model that decides to
    add `limit` to a search must not reach a tool that never offered one, and
    `run(**kwargs)` would accept it silently.

    A tool with exactly one required parameter keeps the near-miss rescue —
    `q` for `query` runs instead of failing — and takes the value only from a
    key the tool never declared. So a search's optional `recency` is never
    mistaken for its query, and a tool with several required parameters gets
    no rescue at all: guessing which value was meant for which name is how a
    booking for Ipoh becomes a booking for two.
    """
    declared = tool.parameters.get("properties") or {}
    bound = {name: arguments[name] for name in declared if name in arguments}

    required = tuple(tool.parameters.get("required") or ())
    if len(required) == 1 and required[0] not in bound:
        strays = [value for key, value in arguments.items() if key not in declared]
        rescued = next((v.strip() for v in strays if isinstance(v, str) and v.strip()), "")
        if rescued:
            bound[required[0]] = rescued
    return bound


def missing_arguments(tool: Tool, bound: dict[str, Any]) -> tuple[str, ...]:
    """Required parameters the model did not usably supply.

    Blank counts as missing. An empty string reaches a tool as an argument and
    comes back as a confusing result rather than a clear refusal.
    """
    required = tuple(tool.parameters.get("required") or ())
    return tuple(
        name
        for name in required
        if bound.get(name) is None
        or (isinstance(bound[name], str) and not bound[name].strip())
    )


def text_parameter(name: str, description: str) -> dict[str, Any]:
    """The common case: one required string argument."""
    return {
        "type": "object",
        "properties": {name: {"type": "string", "description": description}},
        "required": [name],
    }
