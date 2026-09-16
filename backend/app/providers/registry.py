"""The one place that decides which provider is in use.

Adding a provider is a new file implementing `LLMProvider` plus one branch here.
Nothing else in the application needs to change, because nothing else in the
application imports a concrete provider.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.providers.base import LLMProvider
from app.providers.openai_compatible import OpenAICompatibleProvider


def build_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
    )
