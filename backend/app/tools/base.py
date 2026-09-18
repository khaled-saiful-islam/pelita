"""What a tool is.

A tool takes named arguments, does something, and returns results. It also
carries what the UI should say while it runs and what a model needs to know to
choose it — so the chat service can run any tool without knowing which one it is.

That last property is the point. Today the turn decides which tools to run from
a query; when a model does the choosing instead, the same protocol serves, and
only the selection changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

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


def text_parameter(name: str, description: str) -> dict[str, Any]:
    """The common case: one required string argument."""
    return {
        "type": "object",
        "properties": {name: {"type": "string", "description": description}},
        "required": [name],
    }
