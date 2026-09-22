"""Talking to the model that composes artifacts.

A thin layer over the provider, here rather than in the kind because every kind
needs the same two shapes: ask for a small piece of JSON, and stream a long
document. The kind supplies the words.

It is the same `LLMProvider` protocol the chat turn uses, pointed at a
different model with a much larger output budget — the way the vision reader
already works.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.artifacts.base import ArtifactUnavailable
from app.providers.base import (
    ChatMessage,
    ChatRequest,
    LLMProvider,
    ProviderError,
    Role,
    TokenEvent,
    Usage,
    UsageSource,
)
from app.providers.base import UsageEvent as ProviderUsageEvent

logger = logging.getLogger(__name__)

# A model told "no fence" produces one often enough that stripping it is
# cheaper than a retry. Any language tag, not a list of the ones seen so far:
# a stylesheet came back as ```css and was thrown away for it.
_FENCE = re.compile(r"^\s*```[a-z]*\s*|\s*```\s*$", re.IGNORECASE)


@dataclass
class Written:
    """What a streamed call produced. Mutable because it is filled in as the
    stream arrives, and read once it has finished."""

    text: str = ""
    usage: Usage = field(
        default_factory=lambda: Usage(
            prompt_tokens=0, completion_tokens=0, source=UsageSource.ESTIMATED
        )
    )


def strip_fence(text: str) -> str:
    return _FENCE.sub("", text.strip()).strip()


def parse_object(raw: str) -> dict[str, Any]:
    """The first JSON object in the reply, or nothing.

    Returns an empty dict rather than raising: a direction that failed to parse
    means composing from defaults, which is a worse poster and not a failed
    request.
    """
    text = strip_fence(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


class ArtifactModel:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_tokens: int = 16384,
        temperature: float = 0.4,
    ) -> None:
        self._provider = provider
        self._max_tokens = max_tokens
        self._temperature = temperature

    @property
    def name(self) -> str:
        return self._provider.info.model

    async def decide(self, system: str, user: str, *, max_tokens: int = 1600) -> dict[str, Any]:
        """One short call that must return JSON. Not streamed — there is
        nothing to show until it is complete, and it is over in a second."""
        request = ChatRequest(
            messages=(
                ChatMessage(role=Role.SYSTEM, content=system),
                ChatMessage(role=Role.USER, content=user),
            ),
            model=self.name,
            temperature=0.7,
            max_tokens=max_tokens,
            stream=False,
        )
        try:
            completion = await self._provider.complete(request)
        except ProviderError as exc:
            raise ArtifactUnavailable(exc.message) from exc
        return parse_object(completion.text)

    async def write(
        self, system: str, user: str, into: Written, *, temperature: float | None = None
    ) -> AsyncIterator[str]:
        """Stream a long document, yielding it as it arrives.

        Streamed rather than requested whole because a poster is thousands of
        tokens: a non-streaming call sits silent for a minute and then either
        lands or times out, with nothing to show either way.
        """
        request = ChatRequest(
            messages=(
                ChatMessage(role=Role.SYSTEM, content=system),
                ChatMessage(role=Role.USER, content=user),
            ),
            model=self.name,
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=self._max_tokens,
            stream=True,
        )
        pieces: list[str] = []
        try:
            async for event in self._provider.stream_chat(request):
                if isinstance(event, TokenEvent):
                    pieces.append(event.text)
                    yield event.text
                elif isinstance(event, ProviderUsageEvent):
                    into.usage = event.usage
        except ProviderError as exc:
            raise ArtifactUnavailable(exc.message) from exc

        into.text = strip_fence("".join(pieces))
        if not into.text:
            raise ArtifactUnavailable("The model returned nothing to render.")
