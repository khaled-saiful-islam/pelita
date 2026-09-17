"""Attached files, as prompt content.

Order 350 — the slot the registry has reserved for retrieval since the pipeline
was written. Documents are exactly that: material fetched for this turn, read
after standing context and before the conversation's own history.

This is the whole integration. Nothing in the chat service knows that documents
exist beyond loading them, which is what the contributor pipeline was for.
"""

from __future__ import annotations

import logging

from app.context.base import ContextContributor, TurnContext, system
from app.core.tokens import count_tokens
from app.providers.base import ChatMessage
from app.services.document_excerpts import select_excerpts

logger = logging.getLogger(__name__)

HEADER = (
    "The user has attached the following files. Answer from them when the "
    "question relates to their contents, and name the file you used. If a file "
    "does not contain the answer, say so rather than guessing."
)


class DocumentContributor(ContextContributor):
    """Puts attached files in front of the model, within a token budget."""

    name = "documents"
    order = 350

    def __init__(self, budget: int) -> None:
        self._budget = budget

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
        if not ctx.documents:
            return []

        # Shared evenly rather than first-come. Otherwise one long file consumes
        # the budget and a question about the third file is answered from
        # nothing — and the user has no way to know why.
        each = max(1, self._budget // len(ctx.documents))
        blocks: list[str] = [HEADER, ""]

        for document in ctx.documents:
            excerpt, trimmed = select_excerpts(
                document.text, question=ctx.user_message, budget=each, model=ctx.model
            )
            if not excerpt.strip():
                continue
            label = f"{document.filename} ({document.unit_count} {document.unit}"
            label += "s)" if document.unit_count != 1 else ")"
            if trimmed:
                # Said plainly, so the model can qualify its answer rather than
                # asserting something the excerpt does not support.
                label += " — excerpts most relevant to the question"
            blocks.extend([f"--- {label} ---", excerpt, ""])

        if len(blocks) <= 2:
            return []

        body = "\n".join(blocks).strip()
        logger.info(
            "documents contributed %d tokens across %d files",
            count_tokens(body, ctx.model),
            len(ctx.documents),
        )
        return [system(body)]
