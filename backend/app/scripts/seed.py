"""Seed the admin account.

Runs on every container start, so it must be idempotent. `make up` is supposed
to land on an app you can sign into; that is the only reason this exists.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.db.models.user import User
from app.db.repositories.users import SqlUserRepository
from app.db.session import session_scope

logger = logging.getLogger("seed")

INSECURE_DEFAULTS = {"admin", "password", "changeme"}


async def seed_admin() -> None:
    settings = get_settings()
    username = settings.seed_admin_username.strip().lower()
    email = settings.seed_admin_email.strip().lower()

    async with session_scope() as session:
        users = SqlUserRepository(session)
        if await users.get_by_username(username):
            logger.info("admin %r already exists; nothing to do", username)
        else:
            await users.add(
                User(
                    username=username,
                    email=email,
                    password_hash=hash_password(settings.seed_admin_password),
                    display_name="Administrator",
                    is_admin=True,
                    is_active=True,
                )
            )
            logger.info("seeded admin %r <%s>", username, email)

    if settings.seed_admin_password.lower() in INSECURE_DEFAULTS:
        logger.warning(
            "SEED_ADMIN_PASSWORD is still the default. Change it in .env before "
            "exposing this to anyone."
        )


def main() -> None:
    configure_logging(get_settings().log_level)
    asyncio.run(seed_admin())


if __name__ == "__main__":
    main()
