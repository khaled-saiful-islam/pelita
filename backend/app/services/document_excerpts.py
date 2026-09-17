"""Choosing which parts of a document the model sees.

When everything fits the budget, everything goes in. When it does not — and
three files of a few megabytes each will not — the question decides what makes
it: each document is split into chunks, chunks are scored by how much of the
question's vocabulary they contain, and the best ones are kept in their original
order.

Keyword scoring rather than embeddings, deliberately. It needs no extra service,
no vector column and no indexing step, it works offline, and for "what does the
contract say about termination" it picks the right paragraphs. A proper
retriever can later be added as a second contributor at the same order without
touching this one — which is the point of the contributor pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.tokens import count_tokens

CHUNK_TARGET_LINES = 12
# Words too common to distinguish one chunk from another. A short list beats a
# long one: dropping a real term hurts more than keeping a dull one.
_STOPWORDS = (
    "a an and are as at be but by can could do does for from had has have how i "
    "if in is it its me my of on or our so that the their them then there these "
    "they this to was we were what when where which who why will with would you "
    "your"
)
STOPWORDS = frozenset(_STOPWORDS.split())
WORD = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Chunk:
    order: int
    text: str
    tokens: int


def chunk_document(text: str, *, model: str, target_lines: int = CHUNK_TARGET_LINES) -> list[Chunk]:
    """Split on blank lines, then group into chunks of roughly `target_lines`.

    Paragraph boundaries are kept because a paragraph is the unit that makes
    sense on its own; splitting mid-sentence produces excerpts that read as
    broken rather than as brief.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[Chunk] = []
    buffer: list[str] = []
    lines = 0

    def flush() -> None:
        nonlocal buffer, lines
        if buffer:
            body = "\n\n".join(buffer)
            chunks.append(Chunk(order=len(chunks), text=body, tokens=count_tokens(body, model)))
            buffer, lines = [], 0

    for paragraph in paragraphs:
        buffer.append(paragraph)
        lines += paragraph.count("\n") + 1
        if lines >= target_lines:
            flush()
    flush()

    return chunks


def keywords(question: str) -> set[str]:
    """Meaningful words from the question, lowercased."""
    return {
        word.lower()
        for word in WORD.findall(question)
        if len(word) > 2 and word.lower() not in STOPWORDS
    }


def score(chunk: Chunk, terms: set[str]) -> int:
    """How many of the question's terms this chunk contains.

    Distinct terms, not occurrences: a chunk mentioning three of the asked-about
    things beats one repeating a single word thirty times.
    """
    if not terms:
        return 0
    present = {word.lower() for word in WORD.findall(chunk.text)}
    return len(terms & present)


def select_excerpts(text: str, *, question: str, budget: int, model: str) -> tuple[str, bool]:
    """Return `(excerpt, was_trimmed)` for one document.

    The whole document when it fits. Otherwise the highest-scoring chunks that
    fit, restored to document order so the excerpt reads forwards.
    """
    if budget <= 0:
        return "", True
    if count_tokens(text, model) <= budget:
        return text, False

    chunks = chunk_document(text, model=model)
    if not chunks:
        return "", True

    terms = keywords(question)
    # Sort by relevance, then by position, so a document with no matching terms
    # still yields its opening rather than an arbitrary middle.
    ranked = sorted(chunks, key=lambda c: (-score(c, terms), c.order))

    kept: list[Chunk] = []
    used = 0
    for chunk in ranked:
        if used + chunk.tokens > budget:
            continue
        kept.append(chunk)
        used += chunk.tokens

    # Every chunk on its own is larger than the budget. Returning nothing would
    # leave the model unable to say anything about the file *and* unable to say
    # why, which reads to the user as the upload having failed.
    if not kept:
        return _truncate(ranked[0].text, budget=budget, model=model), True

    kept.sort(key=lambda c: c.order)
    return _join(kept), len(kept) < len(chunks)


def _truncate(text: str, *, budget: int, model: str) -> str:
    """Cut `text` to `budget` tokens, ending on a word boundary.

    Binary search over the character count rather than slicing the encoder's
    output, so this stays correct whichever encoding the model uses.
    """
    marker = " […]"
    room = budget - count_tokens(marker, model)
    if room <= 0:
        return ""

    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if count_tokens(text[:middle], model) <= room:
            low = middle
        else:
            high = middle - 1

    cut = text[:low].rstrip()
    boundary = cut.rfind(" ")
    # Only back up to a word boundary if that does not throw most of it away.
    if boundary > len(cut) // 2:
        cut = cut[:boundary]
    return f"{cut}{marker}" if cut else ""


def _join(chunks: list[Chunk]) -> str:
    """Join excerpts, marking where material was skipped.

    The marker matters: without it a model reads two distant passages as
    consecutive and can invent a connection between them.
    """
    parts: list[str] = []
    previous: int | None = None
    for chunk in chunks:
        if previous is not None and chunk.order != previous + 1:
            parts.append("[…]")
        parts.append(chunk.text)
        previous = chunk.order
    return "\n\n".join(parts)
