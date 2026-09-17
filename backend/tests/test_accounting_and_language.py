from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.providers.base import Usage, UsageSource
from app.services.accounting_service import Pricing, price, summarise
from app.services.language_service import (
    MIN_CONFIDENT_LENGTH,
    detect_language,
    language_name,
    reply_instruction,
)

SUPPORTED = ["en", "ms", "ta", "zh", "bn"]

GPT_4O_MINI = Pricing(
    input_per_1m=Decimal("0.15"), output_per_1m=Decimal("0.60"), currency="USD"
)
FREE = Pricing(input_per_1m=Decimal(0), output_per_1m=Decimal(0), currency="USD")


def usage(prompt: int, completion: int, source=UsageSource.PROVIDER) -> Usage:
    return Usage(prompt_tokens=prompt, completion_tokens=completion, source=source)


# --- pricing ------------------------------------------------------------


def test_cost_uses_separate_input_and_output_rates() -> None:
    # 1M in at $0.15 + 1M out at $0.60
    assert price(usage(1_000_000, 1_000_000), GPT_4O_MINI).cost == Decimal("0.750000")


def test_a_realistic_turn_is_priced_to_six_places() -> None:
    result = price(usage(86, 196), GPT_4O_MINI)
    # 86*0.15/1e6 + 196*0.60/1e6 = 0.0000129 + 0.0001176
    assert result.cost == Decimal("0.000131")


def test_six_decimal_places_are_necessary() -> None:
    """At four places every short message would round to zero and read as free."""
    assert price(usage(40, 40), GPT_4O_MINI).cost > 0


def test_zero_rates_produce_zero_cost() -> None:
    assert price(usage(1000, 1000), FREE).cost == 0
    assert FREE.is_free


def test_totals_add_up() -> None:
    result = price(usage(10, 20), GPT_4O_MINI)
    assert result.total_tokens == 30


def test_the_source_is_carried_through_to_the_event() -> None:
    """The UI must be able to say whether a number was measured or guessed."""
    measured = price(usage(10, 10, UsageSource.PROVIDER), GPT_4O_MINI).as_event()
    guessed = price(usage(10, 10, UsageSource.ESTIMATED), GPT_4O_MINI).as_event()
    assert measured["source"] == "provider"
    assert guessed["source"] == "estimated"


def test_pricing_is_read_from_settings() -> None:
    settings = SimpleNamespace(
        llm_price_input_per_1m=1.5, llm_price_output_per_1m=3.0, llm_price_currency="MYR"
    )
    pricing = Pricing.from_settings(settings)
    assert pricing.input_per_1m == Decimal("1.5")
    assert pricing.currency == "MYR"
    assert not pricing.is_free


# --- conversation totals ------------------------------------------------


def message(prompt: int, completion: int, cost: str, source: str | None):
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion, cost=cost, usage_source=source
    )


def test_totals_sum_the_stored_figures() -> None:
    total = summarise(
        [
            message(10, 20, "0.000100", "provider"),
            message(30, 40, "0.000200", "provider"),
        ],
        GPT_4O_MINI,
    )
    assert total["prompt_tokens"] == 40
    assert total["completion_tokens"] == 60
    assert total["total_tokens"] == 100
    assert total["cost"] == Decimal("0.000300")
    assert total["estimated"] is False


def test_one_estimated_message_marks_the_whole_total_estimated() -> None:
    """A total that mixes measured and guessed must not look precise."""
    total = summarise(
        [
            message(10, 20, "0.000100", "provider"),
            message(30, 40, "0.000200", "estimated"),
        ],
        GPT_4O_MINI,
    )
    assert total["estimated"] is True


def test_an_empty_conversation_totals_zero() -> None:
    total = summarise([], GPT_4O_MINI)
    assert total["total_tokens"] == 0
    assert total["cost"] == 0


# --- language detection -------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Explain how monsoons work in Southeast Asia", "en"),
        ("Terangkan bagaimana angin monsun berfungsi di Asia Tenggara", "ms"),
        ("தென்கிழக்கு ஆசியாவில் பருவக்காற்று எப்படி வேலை செய்கிறது", "ta"),
        ("请解释东南亚的季风是如何运作的", "zh"),
        ("দক্ষিণ-পূর্ব এশিয়ায় মৌসুমি বায়ু কীভাবে কাজ করে", "bn"),
    ],
)
def test_every_required_language_is_detected(text: str, expected: str) -> None:
    assert detect_language(text, supported=SUPPORTED, default="en") == expected


@pytest.mark.parametrize("text", ["hi", "ok", "ya", "", "   ", "?"])
def test_short_text_falls_back_rather_than_guessing(text: str) -> None:
    """"hi" and "hai" are indistinguishable; a wrong guess is worse than a default."""
    assert len(text.strip()) < MIN_CONFIDENT_LENGTH
    assert detect_language(text, supported=SUPPORTED, default="en") == "en"


def test_the_default_is_honoured() -> None:
    assert detect_language("hi", supported=SUPPORTED, default="ms") == "ms"


def test_an_unsupported_language_falls_back_to_the_default() -> None:
    """German is not in the list, so it must not be returned."""
    result = detect_language(
        "Erklären Sie mir bitte ausführlich wie der Monsun funktioniert",
        supported=SUPPORTED,
        default="en",
    )
    assert result in SUPPORTED


def test_unknown_codes_are_ignored_not_fatal() -> None:
    assert detect_language(
        "Explain how monsoons work in Southeast Asia",
        supported=["en", "ms", "klingon"],
        default="en",
    ) == "en"


def test_fewer_than_two_languages_disables_detection() -> None:
    """lingua needs something to choose between."""
    assert detect_language(
        "Terangkan bagaimana angin monsun berfungsi", supported=["ms"], default="en"
    ) == "en"


# --- the prompt instruction ---------------------------------------------


def test_language_names_are_human_readable() -> None:
    assert language_name("ms") == "Bahasa Melayu"
    assert language_name("zh") == "Chinese"


def test_an_unknown_code_returns_itself_rather_than_failing() -> None:
    assert language_name("xx") == "xx"


def test_the_instruction_names_the_language_twice() -> None:
    instruction = reply_instruction("ta")
    assert instruction.count("Tamil") == 2
    assert "unless they ask" in instruction
