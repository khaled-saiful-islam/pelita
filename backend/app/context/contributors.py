"""The contributors that ship with the foundation.

Each is small on purpose. A contributor that needs more than a screen of code is
usually two contributors, or a service with a thin contributor in front of it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from urllib.parse import urlparse

from app.context.base import ContextContributor, TurnContext, assistant, system, user
from app.context.pipeline import trim_to_budget
from app.core.clock import long_date
from app.core.tokens import count_tokens
from app.providers.base import ChatMessage, Role, ToolResult
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
            messages.append(system(images_already_shown(images)))
        if documents:
            messages.append(
                system(
                    format_results(documents, model=ctx.model, budget=ctx.budget.tools, now=ctx.now)
                )
            )
        return messages


def images_already_shown(images: Sequence[ToolResult]) -> str:
    """Told to the model because otherwise it says "I cannot show you photos",
    which is false and directly contradicts the grid above its answer."""
    titles = "; ".join(r.title for r in images[:4])
    return (
        f"{len(images)} matching images are already displayed to the user "
        f"above your reply ({titles}). Do not say you cannot show images "
        "and do not list their URLs. Describe or discuss the subject, and "
        "add anything useful the pictures do not convey."
    )


def format_results(
    results: Sequence[ToolResult], *, model: str, budget: int, now: datetime | None = None
) -> str:
    """Numbered, dated results, and the rules for reading them.

    Shared by the contributor and the tool-calling loop, which put the same text
    in different places — a system message when the turn chose the tool, a tool
    message when the model did. One copy, so the citation numbering and the
    instruction cannot drift apart between the two paths.

    The rules are the fix for an answer that read "2024–25 Premier League:
    Liverpool" and "2025/26: Arsenal" in the same set of results and chose the
    older one, because nothing said one was newer or that newer wins.
    """
    lines: list[str] = [grounding(now), ""]
    used = count_tokens("\n".join(lines), model)

    for result in results:
        cost = count_tokens(block := _block(result), model)
        if used + cost > budget:
            break
        lines.extend([block, ""])
        used += cost

    return "\n".join(lines).strip()


def grounding(now: datetime | None) -> str:
    today = f", today, {long_date(now)}" if now else ""
    return (
        f"Web search results, retrieved just now{today}. Answer from them, and cite "
        "the ones you rely on inline as [1], [2] and so on.\n"
        "- Newer beats older. For anything that changes -- a champion, a price, a "
        "score, a version, a schedule, who holds an office -- go with the most "
        'recent dated source, and say when the information is from ("as of 19 May '
        '2026"). A page about an earlier season, year or version describes the '
        "past, not now.\n"
        "- These beat your memory. What you remember is older than they are; where "
        "the two disagree, they are right.\n"
        "- Say only what they support. If they do not answer the question, or "
        "disagree with no way to tell which is newer, say so plainly -- never fill "
        "the gap from memory, and never invent a source.\n"
        "- If the person disputed an earlier answer, these settle it. Say plainly "
        "what they show, whoever that proves right."
    )


def _block(result: ToolResult) -> str:
    host = (urlparse(result.url).hostname or "").removeprefix("www.")
    heading = f"[{result.rank}] {result.title}"
    about = " · ".join(part for part in (host, _dated(result.published)) if part)
    parts = [heading, f"{about} — {result.url}" if about else result.url, result.snippet]
    if result.excerpt:
        parts.append(f"From the page: {result.excerpt}")
    return "\n".join(part for part in parts if part).strip()


def _dated(published: str) -> str:
    if not published:
        return ""
    return published if published.startswith("updated") else f"published {published}"


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
