"""The guards that run on text entering the prompt.

Adding a guard — a PII scrubber, a secrets detector, a profanity filter — is one
file implementing `Guard` and one entry here. Nothing else changes, because the
caller iterates whatever this returns.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.guards.base import Guard
from app.guards.prompt_injection import PromptInjectionGuard


def build_guards(settings: Settings | None = None) -> tuple[Guard, ...]:
    settings = settings or get_settings()
    if not settings.guard_enabled:
        return ()
    return (PromptInjectionGuard(),)
