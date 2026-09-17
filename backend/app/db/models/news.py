from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, uuid_pk


class NewsCache(Base):
    """Cached MCP responses, keyed by the parameters that produced them.

    Cached in Postgres rather than in memory so the strip survives a restart and
    so a cold container does not hammer the MCP server on every boot.
    """

    __tablename__ = "news_cache"

    id: Mapped[uuid_pk] = uuid_pk()
    # tool:language:country — anything that changes the result changes the key.
    cache_key: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    payload: Mapped[list] = mapped_column(JSONB, nullable=False)

    fetched_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
