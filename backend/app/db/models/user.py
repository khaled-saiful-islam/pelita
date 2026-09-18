from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, updated_at, uuid_pk


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid_pk] = uuid_pk()

    # Citext would be tidier, but it needs an extension; lowercasing on the way
    # in keeps the unique index meaningful without one.
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Tokens this account may spend in any rolling 24 hours. NULL is unlimited,
    # which is the default — a template that throttles by surprise is worse
    # than one that does not throttle, and an admin who wants a cap sets one.
    daily_token_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.username}>"
