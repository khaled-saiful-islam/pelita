"""The contributors that ship with the foundation.

Each is small on purpose. A contributor that needs more than a screen of code is
usually two contributors, or a service with a thin contributor in front of it.
"""

from __future__ import annotations

from app.context.base import ContextContributor, TurnContext, assistant, system, user
from app.context.pipeline import trim_to_budget
from app.providers.base import ChatMessage, Role


class SystemPromptContributor(ContextContributor):
    """Opens every prompt. Order 100 so nothing can precede it."""

    name = "system_prompt"
    order = 100

    def __init__(self, prompt: str) -> None:
        self._prompt = prompt.strip()

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
        return [system(self._prompt)] if self._prompt else []


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
