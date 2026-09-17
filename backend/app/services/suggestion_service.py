"""Follow-up suggestions.

Three short questions offered as chips after an answer. Generated with one cheap
non-streaming call once the answer is complete, so they cost nothing until the
user has already got what they asked for — and failing to produce them costs
nothing either.
"""

from __future__ import annotations

import json
import logging

from app.providers.base import ChatMessage, ChatRequest, LLMProvider, Role

logger = logging.getLogger(__name__)

MAX_SUGGESTION_LENGTH = 80

PROMPT = """\
Suggest {count} short follow-up questions the user might ask next, based on the \
exchange below.

Rules:
- Written from the user's point of view, as they would type them.
- Under {max_length} characters each.
- Each should open a genuinely different direction, not rephrase the others.
- Do not suggest anything the answer already covered.

Reply with a JSON array of strings and nothing else.\
"""


async def suggest(
    provider: LLMProvider,
    *,
    user_message: str,
    assistant_message: str,
    count: int = 3,
) -> list[str]:
    """Return up to `count` suggestions. Never raises."""
    if not assistant_message.strip():
        return []

    request = ChatRequest(
        messages=(
            ChatMessage(
                role=Role.SYSTEM,
                content=PROMPT.format(count=count, max_length=MAX_SUGGESTION_LENGTH),
            ),
            ChatMessage(
                role=Role.USER,
                content=f"User: {user_message}\n\nAssistant: {assistant_message[:4000]}",
            ),
        ),
        model=provider.info.model,
        temperature=0.7,
        max_tokens=200,
        stream=False,
    )

    try:
        completion = await provider.complete(request)
    except Exception:  # noqa: BLE001 - chips are optional, the answer is not
        logger.info("suggestion generation failed", exc_info=True)
        return []

    return parse_suggestions(completion.text, count=count)


def parse_suggestions(raw: str, *, count: int) -> list[str]:
    """Locate a JSON array in the response and clean it up.

    Models wrap JSON in prose and fences however they like, so the array is
    found rather than assumed, and anything unparseable yields no chips.
    """
    text = raw.strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    seen: set[str] = set()
    out: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            continue
        cleaned = " ".join(item.split())[:MAX_SUGGESTION_LENGTH].strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= count:
            break
    return out
