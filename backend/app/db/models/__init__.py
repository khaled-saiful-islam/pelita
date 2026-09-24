"""Model registry.

Every model must be imported here so Alembic autogenerate can see it. A model
that is not listed produces a migration that silently drops its table.
"""

from __future__ import annotations

from app.db.models.artifact import Artifact, ArtifactVersion
from app.db.models.artifact_share import ArtifactShare
from app.db.models.artifact_state import ArtifactState
from app.db.models.conversation import Conversation, Message
from app.db.models.document import Document
from app.db.models.feedback import MessageFeedback
from app.db.models.guard_event import GuardEvent
from app.db.models.memory import Memory
from app.db.models.news import NewsCache
from app.db.models.rate_limit import RateLimitHit
from app.db.models.share import ConversationShare
from app.db.models.source import MessageSource
from app.db.models.user import User

__all__ = [
    "Artifact",
    "ArtifactShare",
    "ArtifactState",
    "ArtifactVersion",
    "Conversation",
    "ConversationShare",
    "Document",
    "GuardEvent",
    "Memory",
    "Message",
    "MessageFeedback",
    "MessageSource",
    "NewsCache",
    "RateLimitHit",
    "User",
]
