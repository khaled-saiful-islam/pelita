"""Assembles the message array from an ordered list of contributors.

This module knows nothing about memory, history, retrieval or tools. It sorts,
calls, measures and records. Every feature that needs to put something in front
of the model does so by registering a contributor, which is why adding RAG later
is a new file rather than a rewrite of this one.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.context.base import ContextContributor, TurnContext
from app.core.tokens import count_tokens
from app.providers.base import BuildTrace, ChatMessage

logger = logging.getLogger(__name__)


async def build_messages(
    ctx: TurnContext,
    contributors: Sequence[ContextContributor],
) -> tuple[tuple[ChatMessage, ...], BuildTrace]:
    """Run every contributor in order and return the prompt plus a trace.

    A contributor that raises is skipped rather than allowed to break the turn.
    Losing memory or retrieved documents should degrade an answer, not destroy
    it — and the trace records the skip so the failure stays visible.
    """
    messages: list[ChatMessage] = []
    trace = BuildTrace()

    for contributor in sorted(contributors, key=lambda c: c.order):
        try:
            produced = await contributor.contribute(ctx)
        except Exception:
            logger.exception("context contributor %r failed; skipping", contributor.name)
            trace = trace.with_entry(f"{contributor.name} (failed)", 0, 0)
            continue

        if not produced:
            continue
        tokens = sum(count_tokens(m.content, ctx.model) for m in produced)
        messages.extend(produced)
        trace = trace.with_entry(contributor.name, len(produced), tokens)

    return tuple(messages), trace


def trim_to_budget(
    messages: Sequence[ChatMessage],
    budget: int,
    model: str,
    *,
    keep: str = "newest",
) -> list[ChatMessage]:
    """Drop whole messages until the list fits the budget.

    Whole messages, never partial ones: half a truncated exchange reads to the
    model as a conversation that did not happen. `keep="newest"` drops from the
    front, which is what history wants; `keep="oldest"` drops from the back.
    """
    if budget <= 0:
        return []

    ordered = list(messages) if keep == "newest" else list(reversed(messages))
    kept: list[ChatMessage] = []
    used = 0

    for message in reversed(ordered):
        cost = count_tokens(message.content, model)
        if used + cost > budget:
            break
        kept.append(message)
        used += cost

    kept.reverse()
    return kept if keep == "newest" else list(reversed(kept))
