"""Token counting.

Used for two things: enforcing context budgets before a call, and estimating
usage when a provider does not report it. `tiktoken` is an approximation for
non-OpenAI models, which is exactly why every estimate is labelled as one.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

import tiktoken

_FALLBACK_ENCODING = "cl100k_base"
# Rough chars-per-token when even the fallback encoder is unavailable.
_CHARS_PER_TOKEN = 4


@lru_cache(maxsize=8)
def _encoder(model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding(_FALLBACK_ENCODING)


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    if not text:
        return 0
    try:
        return len(_encoder(model).encode(text, disallowed_special=()))
    except Exception:  # noqa: BLE001 - counting must never break a chat turn
        return max(1, len(text) // _CHARS_PER_TOKEN)


def count_message_tokens(messages: Sequence[object], model: str = "gpt-4o-mini") -> int:
    """Count a message list, including the per-message framing overhead.

    OpenAI's documented approximation is 4 tokens of envelope per message plus
    3 for the reply priming. It is close enough for budgeting on any provider.
    """
    total = 0
    for m in messages:
        content = getattr(m, "content", "")
        total += count_tokens(str(content), model) + 4
    return total + 3
