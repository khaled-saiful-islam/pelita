"""The ordered list of context contributors.

This is the file you edit to change what the model sees. Adding retrieval means
writing `RetrievalContributor` with `order = 350` and adding one line below —
no existing contributor changes, because none of them knows the others exist.

Reserved order values:

    100  system prompt
    150  the date and time         (feature 011)
    200  memory                  (feature 013)
    300  tool results            (feature 011)
    350  attached documents      (feature 018) — and where retrieval belongs
    400  history
    450  a challenge to the last answer
    500  user message
"""

from __future__ import annotations

from app.context.base import ContextContributor
from app.context.clock import ClockContributor
from app.context.contributors import (
    HistoryContributor,
    MemoryContributor,
    SystemPromptContributor,
    ToolResultsContributor,
    UserMessageContributor,
)
from app.context.dispute import DisputeContributor
from app.context.documents import DocumentContributor
from app.core.config import Settings, get_settings


def build_contributors(
    settings: Settings | None = None,
    *,
    memories: tuple[str, ...] = (),
) -> tuple[ContextContributor, ...]:
    settings = settings or get_settings()
    return (
        SystemPromptContributor(settings.system_prompt),
        ClockContributor(),
        MemoryContributor(memories),
        ToolResultsContributor(),
        DocumentContributor(settings.documents_token_budget),
        HistoryContributor(),
        DisputeContributor(),
        UserMessageContributor(),
    )
