"""Conversation export.

Markdown because it is readable as plain text, pastes into almost anything, and
survives being opened in ten years by something that does not exist yet.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.db.models.conversation import Conversation, Message
from app.providers.base import Role

_UNSAFE_FILENAME = re.compile(r"[^\w\s-]")
_WHITESPACE = re.compile(r"[-\s]+")
MAX_FILENAME_LENGTH = 60


def to_markdown(conversation: Conversation, *, app_name: str = "Pelita") -> str:
    """Render a conversation as a Markdown document."""
    lines = [
        f"# {conversation.title}",
        "",
        f"*Exported from {app_name} on {datetime.now().strftime('%-d %B %Y at %H:%M')}*",
        "",
        "---",
        "",
    ]

    for message in conversation.messages:
        lines.extend(_render(message))

    return "\n".join(lines).rstrip() + "\n"


def _render(message: Message) -> list[str]:
    speaker = "You" if message.role == Role.USER else "Assistant"
    lines = [f"## {speaker}", ""]

    content = message.content.strip()
    if content:
        lines.extend([content, ""])
    else:
        lines.extend(["*(no content)*", ""])

    if message.finish_reason == "stopped":
        lines.extend(["*(stopped early)*", ""])

    return lines


def filename_for(conversation: Conversation) -> str:
    """A safe, descriptive filename.

    Built from the title rather than the id so a folder of exports is
    browsable, with the id's first segment appended to keep two conversations
    with the same title apart.
    """
    slug = _UNSAFE_FILENAME.sub("", conversation.title).strip().lower()
    slug = _WHITESPACE.sub("-", slug)[:MAX_FILENAME_LENGTH].strip("-")
    if not slug:
        slug = "conversation"
    return f"{slug}-{str(conversation.id)[:8]}.md"
