"""When the person says the last answer was wrong.

A model's reflex, told it is wrong, is to agree. Told "you are completely
wrong, it is Liverpool", this one said "You're absolutely right, and I
apologize", searched, found Arsenal, and still called its own correct answer
incorrect. Being told is not evidence.

The same rule already stands near the top of the prompt, and was ignored
there. Order 450 puts it directly before the message it is about -- after the
history, before the person's words -- which is where a model reads its most
recent instruction. It is said only when the message pushes back, so an
ordinary turn never pays for it.
"""

from __future__ import annotations

import re

from app.context.base import TurnContext, system
from app.providers.base import ChatMessage, Role

CHALLENGE = re.compile(
    r"(?:"
    r"\byou(?:'re| are)\s+(?:\w+\s+)?(?:wrong|mistaken|incorrect)\b"
    r"|\b(?:that|this|it)(?:'s| is)\s+(?:\w+\s+)?"
    r"(?:wrong|incorrect|false|not\s+(?:true|right|correct))\b"
    r"|\byou\s+made\s+a\s+mistake\b"
    r"|\bare\s+you\s+sure\b"
    r"|\b(?:check|look)\s+(?:it\s+)?again\b"
    r"|^\s*no\s*[,.!]"
    # "salah satu" is "one of", not "wrong".
    r"|\bsalah\b(?!\s+satu)|\b(?:tidak|tak)\s+betul\b|\bsilap\b"
    r"|你错了|不对|错了|不是这样"
    r")",
    re.IGNORECASE,
)

RULE = (
    "The person is challenging your last answer. Being told you are wrong is not "
    'evidence that you are. Do not open with "you\'re right", an apology or any '
    "other agreement, and do not concede anything yet. If it is a question of "
    "fact, search first and answer from what you find: if the results confirm "
    "what you said, say so plainly and cite them; if they show you were wrong, "
    "say that plainly and correct it. Never both at once."
)


def disputes(message: str) -> bool:
    return bool(CHALLENGE.search(message.replace("’", "'")))


class DisputeContributor:
    name = "dispute"
    order = 450

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
        answered = any(m.role is Role.ASSISTANT for m in ctx.history)
        if not answered or not disputes(ctx.user_message):
            return []
        return [system(RULE)]
