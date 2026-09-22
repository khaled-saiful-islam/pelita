"""Changing part of a document instead of writing a new one.

Asked to change the background colour and handed the whole poster, a model
returns a whole poster — a different one. It has done what was asked and
redesigned everything else on the way, and the person who wanted a different
background has lost the layout they liked.

So a change is expressed as replacements: find this exact text, put that in its
place. Everything not named is untouched by construction rather than by
instruction, which is the only version of "do not change anything else" that
actually holds.

The one hazard is a `find` that matches nothing, which is silent in every
implementation that has tried this. Here it is loud: unmatched edits come back
named, the model is told which, and a change that cannot be expressed this way
falls back to a rewrite rather than quietly doing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Long enough that a `find` is anchored to something real. A one-character
# find matches everywhere and means nothing.
MIN_FIND = 8
MAX_EDITS = 12


@dataclass(frozen=True, slots=True)
class Edit:
    find: str
    replace: str


def read_edits(raw: dict[str, Any]) -> tuple[Edit, ...]:
    """The edits a model sent, however it spelled the fields."""
    found = raw.get("edits")
    if not isinstance(found, list):
        return ()

    edits: list[Edit] = []
    for item in found[:MAX_EDITS]:
        if not isinstance(item, dict):
            continue
        find = str(item.get("find") or item.get("old") or "")
        replace = str(item.get("replace") or item.get("new") or "")
        if find:
            edits.append(Edit(find=find, replace=replace))
    return tuple(edits)


def apply_edits(document: str, edits: tuple[Edit, ...]) -> tuple[str, tuple[str, ...]]:
    """The edited document, and what could not be applied.

    Each `find` must appear exactly once. Appearing twice is as bad as
    appearing never: the model meant one of them and cannot say which, and
    changing both is how a poster ends up with two identical headings.
    """
    edited = document
    problems: list[str] = []

    for index, edit in enumerate(edits, 1):
        if len(edit.find.strip()) < MIN_FIND:
            problems.append(f"edit {index}: the text to find is too short to be unique")
            continue
        seen = edited.count(edit.find)
        if seen == 0:
            problems.append(
                f"edit {index}: this text is not in the document: {_short(edit.find)}"
            )
            continue
        if seen > 1:
            problems.append(
                f"edit {index}: this text appears {seen} times, so it is ambiguous: "
                f"{_short(edit.find)}"
            )
            continue
        edited = edited.replace(edit.find, edit.replace, 1)

    return edited, tuple(problems)


def _short(text: str, limit: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else f"{flat[:limit]}…"
