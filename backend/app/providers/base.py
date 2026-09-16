"""Provider protocol and the value types that cross it.

Nothing in this module knows the name of a vendor. That is deliberate: the
moment a provider name appears in shared types, "works with any OpenAI-compatible
endpoint" stops being true and becomes a claim you have to keep re-checking.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str

    def to_wire(self) -> dict[str, str]:
        return {"role": str(self.role), "content": self.content}


@dataclass(frozen=True, slots=True)
class ChatRequest:
    messages: tuple[ChatMessage, ...]
    model: str
    temperature: float = 0.7
    max_tokens: int = 2048
    stream: bool = True


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


StreamEvent = TokenEvent | UsageEvent | FinishEvent


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    usage: Usage
    finish_reason: FinishReason = FinishReason.STOP


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    name: str
    model: str
    base_url: str
    supports_usage_in_stream: bool = True


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


@dataclass(frozen=True, slots=True)
class TokenBudget:
    memory: int
    tools: int
    history: int


def messages_to_wire(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
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
