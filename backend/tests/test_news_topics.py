"""Choosing a news topic from what the user has been asking about."""

from __future__ import annotations

import pytest

from app.providers.base import ChatRequest, Completion, ProviderInfo, Usage, UsageSource
from app.services.news_topics import MIN_SIGNALS, clean_query, derive_query


class StubModel:
    def __init__(self, answer: str = "NONE") -> None:
        self._answer = answer
        self.calls = 0
        self.last_prompt = ""
        self.info = ProviderInfo(name="stub", model="stub-model", base_url="http://stub")

    async def complete(self, req: ChatRequest) -> Completion:
        self.calls += 1
        self.last_prompt = "\n".join(m.content for m in req.messages)
        return Completion(
            text=self._answer,
            usage=Usage(prompt_tokens=1, completion_tokens=1, source=UsageSource.ESTIMATED),
        )

    def stream_chat(self, req):  # pragma: no cover - unused here
        raise NotImplementedError


# --- cleaning the model's answer ----------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Python Docker updates", "Python Docker updates"),
        ("  espresso coffee roasting  ", "espresso coffee roasting"),
        ('"Malaysia technology news"', "Malaysia technology news"),
        ("Malaysia   general\nelection", "Malaysia general election"),
    ],
)
def test_plain_queries_are_accepted(raw: str, expected: str) -> None:
    assert clean_query(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "NONE",
        "none",
        "NONE — not enough information",
        "",
        "   ",
        # Prose rather than a query: punctuation is the tell.
        "Based on the facts, I would suggest: Malaysian politics.",
        "Here is a query for you!",
        "<script>alert(1)</script>",
        "a" * 200,
    ],
)
def test_anything_that_is_not_a_plain_query_is_rejected(raw: str) -> None:
    """A malformed query would search for junk, so the front page is safer."""
    assert clean_query(raw) == ""


# --- deciding whether to personalise at all -----------------------------


async def test_a_new_account_gets_the_general_front_page() -> None:
    """Nothing to go on, so no model call and no personalisation."""
    model = StubModel("Something")
    query = await derive_query(recent_questions=(), memories=(), provider=model)

    assert query == ""
    assert model.calls == 0


async def test_a_single_signal_is_not_enough_to_personalise() -> None:
    model = StubModel("Something")
    query = await derive_query(
        recent_questions=("hello",), memories=(), provider=model
    )

    assert query == ""
    assert model.calls == 0
    assert MIN_SIGNALS == 2


async def test_recent_questions_alone_are_enough() -> None:
    model = StubModel("espresso coffee roasting")
    query = await derive_query(
        recent_questions=(
            "How do I make espresso with a moka pot?",
            "Which beans are best for roasting?",
        ),
        memories=(),
        provider=model,
    )
    assert query == "espresso coffee roasting"


async def test_the_model_can_decline_to_pick_a_topic() -> None:
    """Generic chit-chat should not produce a confidently wrong strip."""
    model = StubModel("NONE")
    query = await derive_query(
        recent_questions=("hi", "thanks", "ok"), memories=(), provider=model
    )
    assert query == ""


# --- what the model is shown --------------------------------------------


async def test_questions_are_labelled_as_the_stronger_signal() -> None:
    model = StubModel("x y z")
    await derive_query(
        recent_questions=("about kubernetes", "about docker"),
        memories=("The user lives in Kuala Lumpur.",),
        provider=model,
    )

    assert "recent questions" in model.last_prompt.lower()
    assert "standing facts" in model.last_prompt.lower()
    assert "kubernetes" in model.last_prompt
    assert "Kuala Lumpur" in model.last_prompt


async def test_only_a_bounded_number_of_questions_is_sent() -> None:
    """A classifier should not cost more than the thing it is classifying."""
    model = StubModel("x y z")
    await derive_query(
        recent_questions=tuple(f"question {i}" for i in range(50)),
        memories=(),
        provider=model,
    )
    assert model.last_prompt.count("question ") <= 12


async def test_very_long_questions_are_truncated() -> None:
    model = StubModel("x y z")
    await derive_query(
        recent_questions=("q " * 500, "another question"), memories=(), provider=model
    )
    assert len(model.last_prompt) < 2000


async def test_blank_questions_do_not_count_as_signal() -> None:
    model = StubModel("something")
    query = await derive_query(
        recent_questions=("   ", "\n"), memories=(), provider=model
    )
    assert query == ""
    assert model.calls == 0


# --- failure ------------------------------------------------------------


async def test_a_failing_model_falls_back_to_the_front_page() -> None:
    class Broken(StubModel):
        async def complete(self, req):
            raise RuntimeError("provider down")

    query = await derive_query(
        recent_questions=("a", "b"), memories=(), provider=Broken()
    )
    assert query == ""
