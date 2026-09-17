"""The news strip.

Wraps the MCP client in a Postgres cache with a TTL, and guarantees the one
behaviour that matters: news never breaks chat. Every failure path returns an
empty list, and the UI hides the strip when it gets one.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.news import NewsCache
from app.tools.news_mcp import NewsItem, NewsMcpConfig, NewsUnavailable, fetch_headlines

logger = logging.getLogger(__name__)


def cache_key(config: NewsMcpConfig) -> str:
    return f"{config.tool}:{config.language}:{config.country}"


class NewsService:
    def __init__(self, session: AsyncSession, config: NewsMcpConfig, ttl_seconds: int) -> None:
        self._session = session
        self._config = config
        self._ttl = ttl_seconds

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
        expires = datetime.now(UTC) + timedelta(seconds=self._ttl)
        payload = [item.as_dict() for item in items]

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
