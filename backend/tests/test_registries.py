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


def test_contributors_match_the_documented_order() -> None:
    """The registry docstring lists these values; they are the contract other
    features slot into, so a change here should be deliberate."""
    contributors = build_contributors(settings_for())
    assert [(c.name, c.order) for c in contributors] == [
        ("system_prompt", 100),
        ("clock", 150),
        ("memory", 200),
        ("tool_results", 300),
        ("documents", 350),
        ("history", 400),
        ("dispute", 450),
        ("user_message", 500),
    ]


def test_retrieval_reads_after_standing_context_and_before_history() -> None:
    """The template's central claim, now occupied: material fetched for this
    turn sits at 350.

    Attached files took the slot without renumbering anything. A vector-store
    retriever replaces that contributor at the same order, so this is asserted
    as a position rather than against a fixed list.
    """
    orders = {c.name: c.order for c in build_contributors(settings_for())}
    retrieval = orders["documents"]
    assert retrieval == 350
    assert orders["memory"] < retrieval < orders["history"]
    assert orders["tool_results"] < retrieval < orders["user_message"]


def test_every_contributor_has_a_distinct_order() -> None:
    """Equal orders sort unpredictably, so the prompt would vary run to run."""
    orders = [c.order for c in build_contributors(settings_for())]
    assert len(orders) == len(set(orders))


def test_the_registry_is_already_in_order() -> None:
    """build_messages sorts anyway, but a registry that reads in execution order
    is the one people can reason about."""
    orders = [c.order for c in build_contributors(settings_for())]
    assert orders == sorted(orders)
