"""Provider protocol and the value types that cross it.

Nothing in this module knows the name of a vendor. That is deliberate: the
moment a provider name appears in shared types, "works with any OpenAI-compatible
endpoint" stops being true and becomes a claim you have to keep re-checking.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    # The result of a tool the model asked for. Its content is what the model
    # reads next; `tool_call_id` is what ties it to the request.
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool the model asked to run.

    `arguments` stays a raw JSON string, exactly as the model produced it.
    Parsing belongs to whoever knows the tool's schema, and a malformed call has
    to survive long enough to be reported rather than blowing up in transit.
    """

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str
    # Set on an assistant message that asked for tools, and on the tool
    # messages answering it. Both default to empty, so every existing
    # contributor keeps building plain messages and needs no change.
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"role": str(self.role), "content": self.content}
        if self.tool_calls:
            wire["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        if self.tool_call_id is not None:
            wire["tool_call_id"] = self.tool_call_id
        return wire


@dataclass(frozen=True, slots=True)
class ChatRequest:
    messages: tuple[ChatMessage, ...]
    model: str
    temperature: float = 0.7
    max_tokens: int = 2048
    stream: bool = True
    # Ready-for-the-wire schemas. The provider stays ignorant of what a tool
    # is; `tools/base.py` knows how to describe one.
    tools: tuple[dict[str, Any], ...] = ()
    # "auto", "none", "required", or a specific function. Passed through
    # untouched — every provider spells the exotic values differently and
    # guessing for them is worse than letting the caller decide.
    tool_choice: str | dict[str, Any] | None = None


class UsageSource(StrEnum):
    """Where token counts came from.

    Providers disagree about whether streaming responses carry a usage block.
    Recording the origin keeps the cost table honest instead of silently
    presenting an estimate as a measurement.
    """

    PROVIDER = "provider"
    ESTIMATED = "estimated"


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    source: UsageSource

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    STOPPED = "stopped"  # cancelled by the user
    ERROR = "error"
    TOOL_CALLS = "tool_calls"  # the model wants a tool run before it answers


# --- Stream events ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenEvent:
    text: str


@dataclass(frozen=True, slots=True)
class UsageEvent:
    usage: Usage


@dataclass(frozen=True, slots=True)
class FinishEvent:
    reason: FinishReason


@dataclass(frozen=True, slots=True)
class ToolCallsEvent:
    """Every tool the model asked for, once the stream has finished asking.

    Emitted whole rather than as deltas: arguments arrive a few characters at a
    time and are useless until complete, and a caller that had to reassemble
    them would be doing the provider's job.
    """

    calls: tuple[ToolCall, ...]


StreamEvent = TokenEvent | UsageEvent | FinishEvent | ToolCallsEvent


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    usage: Usage
    finish_reason: FinishReason = FinishReason.STOP
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    name: str
    model: str
    base_url: str
    supports_usage_in_stream: bool = True
    # Set False the first time a provider rejects a `tools` payload, so the turn
    # falls back to choosing a tool itself rather than losing search entirely.
    supports_tools: bool = True


class ProviderError(RuntimeError):
    """Raised for any upstream failure the caller should surface to a human.

    Carries a message safe to show in the UI; the detailed cause is logged
    server-side rather than leaked to the browser.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@runtime_checkable
class LLMProvider(Protocol):
    """Every model backend implements exactly this.

    Adding a provider means adding one file that satisfies this protocol and
    one line in the registry.
    """

    info: ProviderInfo

    def stream_chat(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        """Yield token, usage and finish events until the response completes."""
        ...

    async def complete(self, req: ChatRequest) -> Completion:
        """Return a whole response at once. Used for titles and suggestions."""
        ...


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Output of a tool, ready to be turned into prompt text by a contributor."""

    tool: str
    title: str
    url: str
    snippet: str
    rank: int = 0
    # Set only by image search. `url` stays the page the image came from, so a
    # citation is always something a person can open and check.
    thumbnail_url: str = ""
    image_url: str = ""
    # When the page says it was written, as the search or the page put it:
    # "May 19, 2026", "3 hours ago". Empty when neither said, never a guess.
    published: str = ""
    # What the page itself says, read after the search, for the model only.
    # The snippet is Google's two lines about a page; this is the paragraph
    # that answers.
    excerpt: str = ""

    @property
    def is_image(self) -> bool:
        return bool(self.thumbnail_url or self.image_url)


@dataclass(frozen=True, slots=True)
class TokenBudget:
    memory: int
    tools: int
    history: int


def messages_to_wire(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    return [m.to_wire() for m in messages]


@dataclass(frozen=True, slots=True)
class BuildTrace:
    """What each context contributor put into the prompt, and what was trimmed.

    Exists so that "why did the model see that?" is answered by reading output
    rather than by reading code.
    """

    entries: tuple[tuple[str, int, int], ...] = field(default_factory=tuple)

    def with_entry(self, name: str, messages: int, tokens: int) -> BuildTrace:
        return BuildTrace(entries=(*self.entries, (name, messages, tokens)))

    def as_dict(self) -> dict[str, dict[str, int]]:
        return {name: {"messages": m, "tokens": t} for name, m, t in self.entries}
