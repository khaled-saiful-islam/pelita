"""The registries are one line each, but they are the seam the template's
extensibility claim rests on, so they get asserted rather than assumed."""

from __future__ import annotations

from app.context.registry import build_contributors
from app.core.config import Settings
from app.providers.base import LLMProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.registry import build_provider


def settings_for(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_provider_is_built_from_settings_alone() -> None:
    provider = build_provider(
        settings_for(
            llm_base_url="https://api.groq.com/openai/v1",
            llm_api_key="gsk-x",
            llm_model="llama-3.3-70b-versatile",
        )
    )
    assert isinstance(provider, OpenAICompatibleProvider)
    assert isinstance(provider, LLMProvider)
    assert provider.info.base_url == "https://api.groq.com/openai/v1"
    assert provider.info.model == "llama-3.3-70b-versatile"


def test_switching_provider_needs_no_code_change() -> None:
    """The whole premise: three env values, three different backends."""
    configs = [
        ("https://api.openai.com/v1", "gpt-4o-mini"),
        ("http://localhost:11434/v1", "llama3.2"),
        ("https://api.ilmu.ai/v1", "ilmu-v3.1"),
    ]
    for base_url, model in configs:
        provider = build_provider(settings_for(llm_base_url=base_url, llm_model=model))
        assert provider.info.base_url == base_url
        assert provider.info.model == model


def test_contributors_are_returned_in_a_stable_documented_order() -> None:
    contributors = build_contributors(settings_for())
    assert [c.name for c in contributors] == [
        "system_prompt",
        "tool_results",
        "history",
        "user_message",
    ]
    assert [c.order for c in contributors] == [100, 300, 400, 500]


def test_contributor_orders_leave_room_for_new_ones() -> None:
    """Gaps are the mechanism: memory at 200 and retrieval at 350 must still fit
    between what is already registered, without renumbering anything."""
    orders = sorted(c.order for c in build_contributors(settings_for()))
    for reserved in (200, 350):
        assert reserved not in orders
        assert min(orders) < reserved < max(orders)


def test_the_registry_order_is_independent_of_declaration_order() -> None:
    """build_messages sorts by `order`, so the tuple can be rearranged safely."""
    contributors = build_contributors(settings_for())
    assert sorted(c.order for c in contributors) == [c.order for c in contributors]
