"""Remembered facts about the user.

Two ways in: typed by the user in settings, or extracted by the model after a
turn. Both are editable and deletable, and both are visible — memory a person
cannot see or correct is a liability rather than a feature.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.model_output import parse_string_array
from app.db.models.memory import Memory
from app.providers.base import ChatMessage, ChatRequest, LLMProvider, Role

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 500
SOURCES = frozenset({"user", "extracted"})

EXTRACTION_PROMPT = """\
From the exchange below, extract durable facts about the user worth remembering \
for future conversations — their name, role, location, preferences, ongoing \
projects, constraints.

Rules:
- Only what the user stated about themselves. Not what the assistant said.
- Nothing transient: not the current question, not one-off requests.
- Each fact one short sentence, third person, starting "The user".
- If there is nothing durable, return an empty array. That is the common case.

Reply with a JSON array of strings and nothing else.\
"""


class MemoryService:
    def __init__(self, session: AsyncSession, *, max_per_user: int = 100) -> None:
        self._session = session
        self._max = max_per_user

    async def list_for(self, user_id: UUID, *, enabled_only: bool = False) -> list[Memory]:
        query = select(Memory).where(Memory.user_id == user_id)
        if enabled_only:
            query = query.where(Memory.enabled.is_(True))
        result = await self._session.execute(query.order_by(Memory.created_at.desc()))
        return list(result.scalars().all())

    async def add(self, user_id: UUID, content: str, *, source: str = "user") -> Memory:
        content = _validate(content)
        if source not in SOURCES:
            raise ValidationError("Memory source must be 'user' or 'extracted'.")

        existing = await self.list_for(user_id)
        if len(existing) >= self._max:
            raise ValidationError(
                f"You have reached the limit of {self._max} memories. Delete some first."
            )
        # Exact duplicates add nothing but tokens.
        if any(m.content.lower() == content.lower() for m in existing):
            raise ValidationError("That is already remembered.")

        memory = Memory(user_id=user_id, content=content, source=source, enabled=True)
        self._session.add(memory)
        await self._session.flush()
        return memory

    async def update(
        self,
        user_id: UUID,
        memory_id: UUID,
        *,
        content: str | None = None,
        enabled: bool | None = None,
    ) -> Memory:
        memory = await self._owned(user_id, memory_id)
        if content is not None:
            memory.content = _validate(content)
        if enabled is not None:
            memory.enabled = enabled
        await self._session.flush()
        return memory

    async def delete(self, user_id: UUID, memory_id: UUID) -> None:
        await self._session.delete(await self._owned(user_id, memory_id))

    async def extract(
        self, provider: LLMProvider, *, user_message: str, assistant_message: str
    ) -> list[str]:
        """Propose facts from one exchange. Never raises.

        Extraction failing must not affect the conversation it came from, so
        every error path returns an empty list.
        """
        request = ChatRequest(
            messages=(
                ChatMessage(role=Role.SYSTEM, content=EXTRACTION_PROMPT),
                ChatMessage(
                    role=Role.USER,
                    content=f"User: {user_message}\n\nAssistant: {assistant_message}",
                ),
            ),
            model=provider.info.model,
            temperature=0.0,
            max_tokens=256,
            stream=False,
        )

        try:
            completion = await provider.complete(request)
        except Exception:  # noqa: BLE001 - extraction is best-effort
            logger.warning("memory extraction failed", exc_info=True)
            return []

        return parse_facts(completion.text)

    async def _owned(self, user_id: UUID, memory_id: UUID) -> Memory:
        memory = await self._session.get(Memory, memory_id)
        # A stranger's memory and a missing one give the same answer.
        if memory is None or memory.user_id != user_id:
            raise NotFoundError("No such memory.")
        return memory


def _validate(content: str) -> str:
    cleaned = " ".join(content.split())
    if not cleaned:
        raise ValidationError("A memory cannot be empty.")
    if len(cleaned) > MAX_CONTENT_LENGTH:
        raise ValidationError(f"A memory must be under {MAX_CONTENT_LENGTH} characters.")
    return cleaned


def parse_facts(raw: str) -> list[str]:
    """Facts proposed by the model, cleaned. Duplicates are left in — `add`
    checks those against what is already stored."""
    return parse_string_array(raw, max_length=MAX_CONTENT_LENGTH)
