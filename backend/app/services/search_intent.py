"""Deciding whether a question needs the web.

Two stages, cheapest first. Most messages are obvious in either direction and
are settled by pattern alone; only the genuinely ambiguous ones cost a model
call. Classifying every message with an LLM would add latency to "write me a
haiku" for no benefit, and classifying none of them is what made "what is the
current weather in KL?" answer from memory.

The decision carries its reason, so the UI can say why it searched rather than
appearing to do it at random.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.providers.base import ChatMessage, ChatRequest, LLMProvider, Role

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SearchDecision:
    needs_search: bool
    reason: str
    # True when a model call was needed, so the cost is attributable.
    used_model: bool = False


# --- stage one: patterns ------------------------------------------------

# Things that are true today and false next week. If one of these appears, the
# model's training data is the wrong source and no classifier call is needed.
NEEDS_CURRENT = re.compile(
    r"\b("
    r"weather|forecast|temperature|rainfall|humidity"
    r"|news|headlines?|breaking"
    r"|today|tonight|tomorrow|yesterday|right now|currently|current(?:ly)?"
    r"|at the moment|these days|so far this"
    r"|latest|newest|most recent|recently|this (?:week|month|year|morning)"
    r"|price of|cost of|how much (?:is|are|does)|exchange rate|stock price|share price"
    r"|who won|who is the current|final score|match result|election result"
    r"|as of (?:today|now|this)"
    r"|(?:just )?(?:released|launched|announced|published) (?:yet|today|this)"
    r"|opening hours|open now|still (?:open|available|running|maintained)"
    r"|version (?:is|number) (?:current|latest)"
    r")\b",
    re.IGNORECASE,
)

# Things the model can do entirely from what it already knows. Searching these
# spends money and seconds for a worse answer.
NEVER_NEEDS_CURRENT = re.compile(
    r"\b("
    r"write (?:me )?(?:a|an|some)|compose|draft|rewrite|rephrase|paraphrase"
    r"|translate|summari[sz]e (?:this|the above|that)"
    r"|refactor|debug|fix (?:this|my|the) (?:code|bug|function|error)"
    r"|what does this (?:code|function|error) (?:do|mean)"
    r"|calculate|compute|solve|convert \d"
    r"|brainstorm|give me ideas|suggest (?:some )?names"
    r")\b",
    re.IGNORECASE,
)

# A fenced code block is someone working on their own code, not asking about
# the world.
CODE_BLOCK = re.compile(r"```")

CLASSIFIER_PROMPT = """\
Decide whether answering the user's message requires looking up current \
information on the web.

Answer YES when the message asks about anything that changes over time, \
anything after your training cutoff, a specific real-world fact you may be \
wrong about, or a named product, company, person or event whose current state \
matters.

Answer NO when the message can be answered from general knowledge, is creative \
or coding work, is about the conversation itself, or is casual conversation.

Reply with exactly one word: YES or NO.\
"""


async def decide(
    message: str,
    *,
    provider: LLMProvider | None = None,
) -> SearchDecision:
    """Return whether this message warrants a web search.

    Never raises: if the classifier fails, the answer is "no search", because a
    slightly stale answer is better than a failed turn.
    """
    text = message.strip()
    if not text:
        return SearchDecision(False, "empty message")

    if CODE_BLOCK.search(text):
        return SearchDecision(False, "contains a code block")

    if NEVER_NEEDS_CURRENT.search(text):
        return SearchDecision(False, "creative or code task")

    if match := NEEDS_CURRENT.search(text):
        return SearchDecision(True, f"mentions {match.group(0).lower()!r}")

    if provider is None:
        return SearchDecision(False, "no classifier available")

    return await _ask_model(text, provider)


async def _ask_model(text: str, provider: LLMProvider) -> SearchDecision:
    request = ChatRequest(
        messages=(
            ChatMessage(role=Role.SYSTEM, content=CLASSIFIER_PROMPT),
            # Truncated: the first part of a message carries the intent, and a
            # classifier should not cost more than the answer.
            ChatMessage(role=Role.USER, content=text[:600]),
        ),
        model=provider.info.model,
        temperature=0.0,
        max_tokens=4,
        stream=False,
    )

    try:
        completion = await provider.complete(request)
    except Exception:  # noqa: BLE001 - a failed classifier must not end the turn
        logger.info("search intent classification failed; not searching", exc_info=True)
        return SearchDecision(False, "classifier unavailable", used_model=True)

    verdict = completion.text.strip().upper()
    needs = verdict.startswith("YES")
    return SearchDecision(needs, "judged by the model", used_model=True)
