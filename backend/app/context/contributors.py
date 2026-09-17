"""The contributors that ship with the foundation.

Each is small on purpose. A contributor that needs more than a screen of code is
usually two contributors, or a service with a thin contributor in front of it.
"""

from __future__ import annotations

from app.context.base import ContextContributor, TurnContext, assistant, system, user
from app.context.pipeline import trim_to_budget
from app.core.tokens import count_tokens
from app.providers.base import ChatMessage, Role
from app.services.language_service import reply_instruction


class SystemPromptContributor(ContextContributor):
    """Opens every prompt. Order 100 so nothing can precede it."""

    name = "system_prompt"
    order = 100

    def __init__(self, prompt: str) -> None:
        self._prompt = prompt.strip()

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
        parts = [self._prompt] if self._prompt else []
        if ctx.language:
            parts.append(reply_instruction(ctx.language))
        return [system("\n\n".join(parts))] if parts else []


class MemoryContributor(ContextContributor):
    """Remembered facts about the user.

    Order 200: after the system prompt, before anything from this turn, so
    standing facts read as background rather than as something just said.

    Facts are passed in rather than fetched here, because a contributor that
    opens a database session is a contributor that can make a turn fail on a
    connection pool exhaustion.
    """

    name = "memory"
    order = 200

    def __init__(self, facts: tuple[str, ...] = ()) -> None:
        self._facts = facts

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
        if not self._facts:
            return []

        header = "What you know about this user:"
        lines = [header]
        used = count_tokens(header, ctx.model)

        for fact in self._facts:
            cost = count_tokens(fact, ctx.model) + 2
            if used + cost > ctx.budget.memory:
                break
            lines.append(f"- {fact}")
            used += cost

        # Only the header survived the budget, so there is nothing to say.
        if len(lines) == 1:
            return []
        return [system("\n".join(lines))]


class ToolResultsContributor(ContextContributor):
    """Search results and anything else a tool produced.

    Order 300: after standing context, before history, so the model reads the
    fresh material as the most recently established facts rather than as part of
    an old exchange.

    Results are numbered and the model is told to cite them, which is what makes
    the source list under an answer correspond to the text above it.
    """

    name = "tool_results"
    order = 300

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
        if not ctx.tool_results:
            return []

        images = [r for r in ctx.tool_results if r.is_image]
        documents = [r for r in ctx.tool_results if not r.is_image]

        messages: list[ChatMessage] = []
        if images:
            # Without this the model says "I cannot show you photos", which is
            # false and directly contradicts the grid rendered above its answer.
            titles = "; ".join(r.title for r in images[:4])
            messages.append(
                system(
                    f"{len(images)} matching images are already displayed to the user "
                    f"above your reply ({titles}). Do not say you cannot show images "
                    "and do not list their URLs. Describe or discuss the subject, and "
                    "add anything useful the pictures do not convey."
                )
            )

        if not documents:
            return messages

        lines: list[str] = [
            "Search results are given below. Use them to answer, and cite the "
            "ones you rely on inline as [1], [2] and so on. If they do not "
            "answer the question, say so rather than inventing a source.",
            "",
        ]
        used = count_tokens("\n".join(lines), ctx.model)

        for result in documents:
            block = f"[{result.rank}] {result.title}\n{result.url}\n{result.snippet}".strip()
            cost = count_tokens(block, ctx.model)
            if used + cost > ctx.budget.tools:
                break
            lines.extend([block, ""])
            used += cost

        messages.append(system("\n".join(lines).strip()))
        return messages


class HistoryContributor(ContextContributor):
    """Prior turns, trimmed to `budget.history` from the oldest end.

    Order 400: after anything that establishes standing context, before the
    message being answered.
    """

    name = "history"
    order = 400

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
        if not ctx.history:
            return []
        messages = [
            assistant(m.content) if m.role is Role.ASSISTANT else user(m.content)
            for m in ctx.history
            if m.content.strip()
        ]
        return trim_to_budget(messages, ctx.budget.history, ctx.model)


class UserMessageContributor(ContextContributor):
    """The message being answered. Order 500 so it always lands last."""

    name = "user_message"
    order = 500

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
        return [user(ctx.user_message)] if ctx.user_message.strip() else []
