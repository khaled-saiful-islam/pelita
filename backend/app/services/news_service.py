"""The news strip.

Wraps the MCP client in a Postgres cache with a TTL, and guarantees the one
behaviour that matters: news never breaks chat. Every failure path returns an
empty list, and the UI hides the strip when it gets one.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.news import NewsCache
from app.db.repositories.conversations import SqlConversationRepository
from app.providers.base import LLMProvider
from app.services.memory_service import MemoryService
from app.services.news_topics import MAX_RECENT_QUESTIONS, derive_query
from app.tools.news_mcp import NewsItem, NewsMcpConfig, NewsUnavailable, fetch_headlines

logger = logging.getLogger(__name__)


def cache_key(config: NewsMcpConfig) -> str:
    """Anything that changes the result changes the key.

    The query is included, so two users with different interests do not share a
    cache entry — and users with the same interests still do.
    """
    base = f"{config.effective_tool}:{config.language}:{config.country}"
    return f"{base}:{config.query.lower()}" if config.query else base


class NewsService:
    def __init__(self, session: AsyncSession, config: NewsMcpConfig, ttl_seconds: int) -> None:
        self._session = session
        self._config = config
        self._ttl = ttl_seconds

    async def personalised(
        self, *, user_id: UUID, provider: LLMProvider, max_per_user: int
    ) -> tuple[list[NewsItem], bool, str]:
        """Headlines shaped by what Pelita remembers about this user.

        Returns `(items, from_cache, query)`. An empty query means the general
        front page — which is also the fallback whenever anything is uncertain,
        since an irrelevant personalised strip is worse than a generic one.
        """
        query = await self._topic_for(user_id, provider, max_per_user)

        if query:
            self._config = replace(self._config, query=query)
            items, cached = await self.headlines()
            if items:
                return items, cached, query
            # The search found nothing worth showing. Fall through to the
            # general feed rather than leaving the strip empty.
            logger.info("personalised news for %r was empty; using headlines", query)
            self._config = replace(self._config, query="")

        items, cached = await self.headlines()
        return items, cached, ""

    async def _topic_for(
        self, user_id: UUID, provider: LLMProvider, max_per_user: int
    ) -> str:
        """The search query for this user, cached for the same TTL as the news.

        Cached so the new-chat screen does not cost a model call every time it
        loads. It refreshes on the same clock as the headlines, which is the
        right cadence: the topic should move as the conversation does, but not
        on every page view.
        """
        topic_key = f"topic:{user_id}"
        row = await self._row(topic_key)
        if row is not None and row.expires_at > datetime.now(UTC):
            stored = row.payload
            return stored[0] if stored else ""

        query = ""
        try:
            repo = SqlConversationRepository(self._session)
            questions = await repo.recent_user_messages(
                user_id, limit=MAX_RECENT_QUESTIONS
            )
            memories = await MemoryService(
                self._session, max_per_user=max_per_user
            ).list_for(user_id, enabled_only=True)

            query = await derive_query(
                recent_questions=tuple(questions),
                memories=tuple(m.content for m in memories),
                provider=provider,
            )
        except Exception:  # noqa: BLE001 - never break the strip over this
            logger.exception("could not derive a news topic for %s", user_id)
            return ""

        # Cached either way: "no good topic" is an answer worth remembering, or
        # every load re-asks the model to tell us nothing.
        await self._store_payload(topic_key, [query] if query else [])
        return query

    async def headlines(self) -> tuple[list[NewsItem], bool]:
        """Return `(items, from_cache)`. Never raises."""
        key = cache_key(self._config)

        cached = await self._fresh(key)
        if cached is not None:
            return cached, True

        try:
            items = await fetch_headlines(self._config)
        except NewsUnavailable as exc:
            logger.info("news unavailable, hiding strip: %s", exc)
            # Serve stale rather than nothing: yesterday's headlines beat an
            # empty strip when the MCP server is briefly down.
            stale = await self._any(key)
            return (stale or []), stale is not None
        except Exception:  # noqa: BLE001 - news must never break the page
            logger.exception("unexpected failure fetching news")
            return [], False

        await self._store(key, items)
        return items, False

    # -- cache -----------------------------------------------------------

    async def _row(self, key: str) -> NewsCache | None:
        result = await self._session.execute(
            select(NewsCache).where(NewsCache.cache_key == key)
        )
        return result.scalar_one_or_none()

    async def _fresh(self, key: str) -> list[NewsItem] | None:
        row = await self._row(key)
        if row is None or row.expires_at <= datetime.now(UTC):
            return None
        return _decode(row.payload)

    async def _any(self, key: str) -> list[NewsItem] | None:
        row = await self._row(key)
        return _decode(row.payload) if row else None

    async def _store(self, key: str, items: list[NewsItem]) -> None:
        await self._store_payload(key, [item.as_dict() for item in items])

    async def _store_payload(self, key: str, payload: list) -> None:
        expires = datetime.now(UTC) + timedelta(seconds=self._ttl)

        row = await self._row(key)
        if row is None:
            self._session.add(
                NewsCache(cache_key=key, payload=payload, expires_at=expires)
            )
        else:
            row.payload = payload
            row.expires_at = expires
            row.fetched_at = datetime.now(UTC)
        await self._session.flush()


def _decode(payload: list) -> list[NewsItem]:
    return [
        NewsItem(
            title=item.get("title", ""),
            url=item.get("url", ""),
            source=item.get("source", "News"),
            published_at=item.get("published_at"),
            snippet=item.get("snippet", ""),
        )
        for item in payload
        if item.get("title") and item.get("url")
    ]
