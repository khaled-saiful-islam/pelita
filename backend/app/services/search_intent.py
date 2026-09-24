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
    # True when the user asked to be shown something, not told about it.
    wants_images: bool = False


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

# The date and the time, asked for on their own. They are in the prompt, so
# searching for them found the Today Show instead. "The date of the next GE"
# is not this: only the clock itself, and nothing after it.
ASKS_THE_CLOCK = re.compile(
    r"^\s*(?:"
    r"what(?:'s| is)\s+(?:the\s+)?(?:current\s+|today'?s\s+)?(?:date|time|day)"
    r"(?:\s+(?:is it\s+)?(?:today|now|right now))?"
    r"|what\s+(?:day|time|date)\s+is\s+it(?:\s+(?:today|now|right now))?"
    r"|(?:today'?s\s+)?date\s+today"
    r"|tarikh\s+hari\s+ini|hari\s+ini\s+hari\s+apa|(?:pukul|jam)\s+berapa\s+sekarang"
    r")\s*[?.!]*\s*$",
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

# "Show me X" is a different request from "tell me about X". Detected by pattern
# alone: the phrasings are few and explicit, and a model call to recognise
# "picture of" would be spending money to read English.
WANTS_IMAGES = re.compile(
    r"\b("
    r"(?:show|find|get|give|send)\s+(?:me\s+)?(?:some\s+|a\s+|an\s+|the\s+)?"
    r"(?:picture|pictures|photo|photos|image|images|pic|pics|screenshot|screenshots)\b"
    r"|(?:picture|photo|image|pics?|photos|images)\s+of\b"
    r"|what\s+(?:does|do|did)\s+.{1,60}?\s+look\s+like"
    r"|how\s+does\s+.{1,60}?\s+look\b"
    r"|\b(?:diagram|illustration|poster|artwork|logo)\s+of\b"
    r")",
    re.IGNORECASE,
)

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
    has_documents: bool = False,
) -> SearchDecision:
    """Return whether this message warrants a web search.

    `has_documents` says files are attached to this conversation, which changes
    the default for anything ambiguous: someone who attached a brief and asks
    about "the budget" means the brief, not the web.

    Never raises: if the classifier fails, the answer is "no search", because a
    slightly stale answer is better than a failed turn.
    """
    text = message.strip()
    if not text:
        return SearchDecision(False, "empty message")

    # Checked before the negative patterns: "show me a picture of a moka pot"
    # contains no creative-task words, but "draw me a picture" would, and the
    # image intent is the more specific reading either way.
    if match := WANTS_IMAGES.search(text):
        return SearchDecision(
            True, f"asked to see {match.group(0).lower()!r}", wants_images=True
        )

    if CODE_BLOCK.search(text):
        return SearchDecision(False, "contains a code block")

    if ASKS_THE_CLOCK.match(text):
        return SearchDecision(False, "the date and time are known")

    if NEVER_NEEDS_CURRENT.search(text):
        return SearchDecision(False, "creative or code task")

    if match := NEEDS_CURRENT.search(text):
        return SearchDecision(True, f"mentions {match.group(0).lower()!r}")

    if has_documents:
        # Explicit time-sensitive wording above still searches; everything else
        # is assumed to be about the files, and costs no classifier call.
        return SearchDecision(False, "answering from the attached files")

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
