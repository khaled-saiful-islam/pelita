"""Turning what Pelita remembers about you into a news query.

The strip is more useful when it reflects what you actually talk about. The
facts are already there — memory exists for the prompt — so this reuses them
rather than asking anyone to configure interests.

Deliberately conservative. A wrong topic makes the strip irrelevant, which is
worse than a generic strip, so anything uncertain falls back to general
headlines.
"""

from __future__ import annotations

import logging
import re

from app.providers.base import ChatMessage, ChatRequest, LLMProvider, Role

logger = logging.getLogger(__name__)

MAX_QUERY_LENGTH = 80
# Below this there is not enough signal to beat the general front page, which is
# the right answer for a new account rather than a guess from one message.
MIN_SIGNALS = 2
MAX_RECENT_QUESTIONS = 12
MAX_QUESTION_LENGTH = 160

PROMPT = """\
Write one short news search query — three to six words — for headlines this \
person would want to read.

You are given their recent questions and, sometimes, standing facts about them. \
Weight the recent questions much more heavily: what someone is asking about now \
is what they want to read about now. Use the standing facts only to disambiguate \
or to add a location.

Rules:
- Only subjects actually present in the input. Invent nothing.
- Name subjects, not the person: topics, technologies, places, industries.
- No names of individuals and nothing about their private life.
- If there is too little to go on, or the questions are generic chit-chat, \
coding help or creative writing, reply with exactly: NONE

Reply with the query alone, or NONE.\
"""

# A query is a few plain words. Anything else is the model explaining itself.
SAFE_QUERY = re.compile(r"^[\w\s\-&']{3,80}$", re.UNICODE)


async def derive_query(
    *,
    recent_questions: tuple[str, ...],
    memories: tuple[str, ...],
    provider: LLMProvider,
) -> str:
    """Return a search query, or "" to mean "just use the front page".

    Never raises: a personalised strip is a nicety, and the general one is
    always available.
    """
    questions = [q.strip()[:MAX_QUESTION_LENGTH] for q in recent_questions if q.strip()]
    questions = questions[:MAX_RECENT_QUESTIONS]

    if len(questions) + len(memories) < MIN_SIGNALS:
        return ""

    sections: list[str] = []
    if questions:
        sections.append(
            "Their recent questions, newest first:\n"
            + "\n".join(f"- {q}" for q in questions)
        )
    if memories:
        sections.append(
            "Standing facts about them:\n" + "\n".join(f"- {m}" for m in memories[:20])
        )

    request = ChatRequest(
        messages=(
            ChatMessage(role=Role.SYSTEM, content=PROMPT),
            ChatMessage(role=Role.USER, content="\n\n".join(sections)),
        ),
        model=provider.info.model,
        temperature=0.0,
        max_tokens=24,
        stream=False,
    )

    try:
        completion = await provider.complete(request)
    except Exception:  # noqa: BLE001 - fall back to general headlines
        logger.info("news topic derivation failed", exc_info=True)
        return ""

    return clean_query(completion.text)


def clean_query(raw: str) -> str:
    """Accept a plain query, reject anything that looks like prose or markup."""
    candidate = " ".join(raw.strip().strip("\"'").split())
    if not candidate or candidate.upper().startswith("NONE"):
        return ""
    if len(candidate) > MAX_QUERY_LENGTH:
        return ""
    if not SAFE_QUERY.match(candidate):
        # Punctuation, quotes or a sentence means the model answered in prose
        # rather than with a query. A malformed query would search for junk.
        return ""
    return candidate
