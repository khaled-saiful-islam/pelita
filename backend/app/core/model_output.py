"""Reading structured data out of a model's reply.

Models are asked for a JSON array and answer with one wrapped in prose, fenced
in backticks, or nested in an object. This finds the array rather than assuming
the whole reply is one, and returns nothing when it cannot — which is the safe
direction for output that writes to a user's profile.

Shared because two callers needed exactly this and each had grown its own copy.
"""

from __future__ import annotations

import json


def parse_string_array(
    raw: str,
    *,
    max_length: int,
    limit: int | None = None,
    dedupe: bool = False,
) -> list[str]:
    """Extract a list of cleaned strings from a model reply.

    `limit` caps how many are returned; `dedupe` drops case-insensitive repeats,
    which matters for suggestions (three near-identical chips are one chip) and
    not for facts (the caller checks those against what is already stored).
    """
    array = _locate_array(raw)
    if array is None:
        return []

    seen: set[str] = set()
    out: list[str] = []

    for item in array:
        if not isinstance(item, str):
            continue
        cleaned = " ".join(item.split())[:max_length].strip()
        if not cleaned:
            continue
        if dedupe:
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
        out.append(cleaned)
        if limit is not None and len(out) >= limit:
            break

    return out


def _locate_array(raw: str) -> list | None:
    """Find the outermost JSON array in a reply.

    An array nested in an object — `{"suggestions": [...]}` — is recovered too,
    because that is what models answer when asked for a bare array, and the
    difference between working on most providers and working on the one it was
    written against.
    """
    text = raw.strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None
