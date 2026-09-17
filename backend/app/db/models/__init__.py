"""Model registry.

Every model must be imported here so Alembic autogenerate can see it. A model
that is not listed produces a migration that silently drops its table.
"""

from __future__ import annotations

from app.db.models.conversation import Conversation, Message
from app.db.models.feedback import MessageFeedback
from app.db.models.memory import Memory
from app.db.models.news import NewsCache
from app.db.models.source import MessageSource
from app.db.models.user import User

__all__ = [
    "Conversation",
    "Memory",
    "Message",
    "MessageFeedback",
    "MessageSource",
    "NewsCache",
    "User",
]
