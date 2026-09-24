"""Changing the words on an artifact without asking a model.

The commonest edit is a typo, a price or a date. Sending that through a model
costs thirty seconds, a few thousand tokens and a small chance of the poster
coming back subtly different, to change six characters.

So the words are addressable. A document is split into tags and the text
between them; the text runs are numbered in document order, and an edit names
a number and a new string. Everything else in the document — every tag, every
attribute, every byte of CSS — is copied through untouched, which is what makes
this safe to do with no model checking the result.

The browser walks the same document in the same order, so the numbering the
person edited against is the numbering applied here.
"""

from __future__ import annotations

import re
from html import escape, unescape

# Tags and the text between them. Text in a valid document never contains `<`,
# so alternate segments are exactly the runs of text.
_SEGMENTS = re.compile(r"(<[^>]*>)")
# `template` and `noscript` too: the browser editing the words never walks a
# template's contents, and is told to skip noscript, so counting either here
# would shift every number after it by the runs inside.
_OPEN = re.compile(r"<\s*(script|style|template|noscript)\b", re.IGNORECASE)
_CLOSE = re.compile(r"<\s*/\s*(script|style|template|noscript)\s*>", re.IGNORECASE)
# The browser numbers what it can see, walking from <body>. Anything above it —
# the <title> most of all — is not words on the poster, and counting it here
# shifts every number by one and edits the run next to the one somebody meant.
_BODY = re.compile(r"<\s*body\b", re.IGNORECASE)

# The longest a single run may become. A poster is not a document editor, and
# an unbounded field is a way to make a 10MB row out of a text box.
MAX_RUN = 2000


def _runs(document: str) -> list[tuple[int, str]]:
    """Every editable text run, as (segment index, text).

    Anything inside `<style>` is skipped: it is a stylesheet, not words on the
    poster, and letting it be edited here is how a colour becomes `#ff0000;}`.
    """
    segments = _SEGMENTS.split(document)
    found: list[tuple[int, str]] = []
    skipping = False
    # A document with no <body> tag at all is all body, which is what a
    # fragment is.
    started = not _BODY.search(document)
    for index, segment in enumerate(segments):
        if index % 2:  # a tag
            if _BODY.match(segment):
                started = True
            elif _OPEN.match(segment):
                skipping = True
            elif _CLOSE.match(segment):
                skipping = False
            continue
        if not started or skipping or not segment.strip():
            continue
        found.append((index, segment))
    return found


def readable_text(document: str) -> list[str]:
    """What a person would see, in the order they would see it.

    Entities are decoded, because `&nbsp;` is a space on the poster and a
    caller comparing its own reading against this one should not have to know
    how the document happens to spell it. Text goes back in escaped, so the
    round trip is symmetric.
    """
    return [unescape(text).strip() for _, text in _runs(document)]


def apply_text(document: str, changes: dict[int, str]) -> str:
    """Replace numbered text runs, leaving everything else byte for byte.

    A number nobody recognises is ignored rather than raising: the document may
    have been edited by somebody else in the meantime, and losing one correction
    is better than losing all of them.
    """
    if not changes:
        return document

    segments = _SEGMENTS.split(document)
    for position, (index, original) in enumerate(_runs(document)):
        if position not in changes:
            continue
        replacement = changes[position][:MAX_RUN]
        # The surrounding whitespace is layout, not words. Keeping it means an
        # edit cannot silently reflow the document it is in.
        leading = original[: len(original) - len(original.lstrip())]
        trailing = original[len(original.rstrip()) :]
        segments[index] = f"{leading}{escape(replacement, quote=False)}{trailing}"
    return "".join(segments)
