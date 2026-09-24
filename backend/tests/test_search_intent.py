"""Search-intent classification.

The heuristic stage is the point: it has to settle the common cases without a
model call, or auto-detection costs a round trip on every "write me a haiku".
These tests pass no provider, so anything reaching the model stage is visible as
`needs_search is False, reason == "no classifier available"`.
"""

from __future__ import annotations

import pytest

from app.providers.base import ChatRequest, Completion, ProviderInfo, Usage, UsageSource
from app.services.search_intent import decide


class StubClassifier:
    """Answers whatever it is told, and counts how often it was asked."""

    def __init__(self, answer: str = "NO") -> None:
        self._answer = answer
        self.calls = 0
        self.info = ProviderInfo(name="stub", model="stub-model", base_url="http://stub")

    async def complete(self, req: ChatRequest) -> Completion:
        self.calls += 1
        return Completion(
            text=self._answer,
            usage=Usage(prompt_tokens=1, completion_tokens=1, source=UsageSource.ESTIMATED),
        )

    def stream_chat(self, req):  # pragma: no cover - unused here
        raise NotImplementedError


# --- settled by pattern, no model call ----------------------------------

NEEDS_SEARCH = [
    "What is the current weather in KL?",
    "Will it rain in Penang tomorrow?",
    "What's the forecast for this week?",
    "Any news about the budget?",
    "What are today's headlines?",
    "What is the latest version of Python?",
    "Who won the match last night?",
    "What is the price of gold right now?",
    "How much is the USD to MYR exchange rate?",
    "Is that library still maintained?",
    "What did they announce this week?",
    "What are the opening hours?",
]


@pytest.mark.parametrize("message", NEEDS_SEARCH, ids=lambda m: m[:38])
async def test_time_sensitive_questions_search_without_a_model_call(message: str) -> None:
    classifier = StubClassifier("NO")
    decision = await decide(message, provider=classifier)

    assert decision.needs_search, message
    assert not decision.used_model, "should have been settled by pattern"
    assert classifier.calls == 0


NEVER_SEARCH = [
    "Write me a haiku about lanterns",
    "Compose an email declining the meeting",
    "Rewrite this paragraph to be shorter",
    "Translate this into Malay",
    "Summarise the above",
    "Refactor this function to be pure",
    "Debug this error for me",
    "Fix my code please",
    "Calculate 17% of 4300",
    "Brainstorm names for a coffee shop",
]


@pytest.mark.parametrize("message", NEVER_SEARCH, ids=lambda m: m[:38])
async def test_creative_and_code_tasks_never_search(message: str) -> None:
    classifier = StubClassifier("YES")
    decision = await decide(message, provider=classifier)

    assert not decision.needs_search, message
    assert classifier.calls == 0, "should not have consulted the model"


async def test_a_code_block_means_the_user_is_working_on_their_own_code() -> None:
    classifier = StubClassifier("YES")
    decision = await decide("What does this do?\n```python\nx = 1\n```", provider=classifier)

    assert not decision.needs_search
    assert decision.reason == "contains a code block"
    assert classifier.calls == 0


async def test_an_empty_message_searches_for_nothing() -> None:
    assert not (await decide("   ")).needs_search


# --- the ambiguous middle -----------------------------------------------


async def test_ambiguous_questions_are_put_to_the_model() -> None:
    classifier = StubClassifier("YES")
    decision = await decide("Tell me about the Petronas Towers", provider=classifier)

    assert decision.needs_search
    assert decision.used_model
    assert classifier.calls == 1


async def test_the_model_can_decline_to_search() -> None:
    classifier = StubClassifier("NO")
    decision = await decide("Explain how recursion works", provider=classifier)

    assert not decision.needs_search
    assert decision.used_model


@pytest.mark.parametrize("answer", ["YES", "yes", "Yes.", "YES\n"])
async def test_the_models_answer_is_read_leniently(answer: str) -> None:
    assert (await decide("Tell me about X", provider=StubClassifier(answer))).needs_search


@pytest.mark.parametrize("answer", ["NO", "maybe", "", "I think so"])
async def test_anything_but_yes_means_no(answer: str) -> None:
    """A classifier that rambles must not be read as agreement."""
    assert not (await decide("Tell me about X", provider=StubClassifier(answer))).needs_search


async def test_without_a_classifier_ambiguous_means_no_search() -> None:
    decision = await decide("Tell me about the Petronas Towers")
    assert not decision.needs_search
    assert decision.reason == "no classifier available"


async def test_a_failing_classifier_does_not_end_the_turn() -> None:
    class Broken(StubClassifier):
        async def complete(self, req):
            raise RuntimeError("provider down")

    decision = await decide("Tell me about X", provider=Broken())
    assert not decision.needs_search
    assert decision.reason == "classifier unavailable"


# --- transparency -------------------------------------------------------


async def test_the_reason_names_the_phrase_that_triggered_it() -> None:
    """The UI shows this, so a search never looks like it happened at random."""
    decision = await decide("What is the current weather in KL?")
    assert "current" in decision.reason


# --- the clock ----------------------------------------------------------

ASKS_THE_CLOCK = [
    "what is the current date?",
    "What's today's date",
    "what day is it today?",
    "what time is it now",
    "What is the date today?",
    "tarikh hari ini?",
    "pukul berapa sekarang",
]


@pytest.mark.parametrize("message", ASKS_THE_CLOCK)
async def test_the_date_and_time_are_known_not_searched(message: str) -> None:
    """Searched, "what is the current date?" came back with the Today Show."""
    decision = await decide(message, provider=StubClassifier("YES"))
    assert not decision.needs_search
    assert not decision.used_model


async def test_a_question_about_a_date_is_still_a_question_about_the_world() -> None:
    """The date *of something* is not the clock: it goes on to be judged."""
    decision = await decide("what is the date of the next GE?", provider=StubClassifier("YES"))
    assert decision.needs_search and decision.used_model
