"""Being told it is wrong is not evidence that it is.

The regression: "you are completely wrong, it is Liverpool" was answered
"You're absolutely right, and I apologize" -- and then, from search results
showing Arsenal, "My previous answer was incorrect". It had been correct. A
rule to check first, standing at the top of a long prompt, was not enough;
said again right before the message it is about, it is.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.context.base import StoredMessage, TurnContext
from app.context.dispute import DisputeContributor, disputes
from app.context.registry import build_contributors
from app.providers.base import Role

ANSWERED = (
    StoredMessage(role=Role.USER, content="who is the current EPL champion?"),
    StoredMessage(role=Role.ASSISTANT, content="Arsenal, as of May 2026."),
)


def ctx(message: str, history=ANSWERED) -> TurnContext:
    return TurnContext(
        conversation_id=uuid4(),
        user_id=uuid4(),
        user_message=message,
        model="gpt-4o-mini",
        history=history,
    )


@pytest.mark.parametrize(
    "message",
    [
        "you are completely wrong, it is Liverpool",
        "You're wrong",
        "that's not true",
        "That is incorrect, check again",
        "no, it's Liverpool",
        "are you sure? I think it's Liverpool",
        "salah, Liverpool juara",
        "itu tidak betul",
        "你错了，是利物浦",
    ],
)
def test_a_challenge_is_recognised(message: str) -> None:
    assert disputes(message)


@pytest.mark.parametrize(
    "message",
    [
        "what went wrong at the 2026 World Cup final?",
        "no worries, thanks",
        "is it wrong to eat durian with alcohol?",
        "make me a poster about Liverpool",
        "salah satu pasukan terbaik ialah Arsenal",
    ],
)
def test_an_ordinary_message_is_not(message: str) -> None:
    assert not disputes(message)


async def test_a_challenge_gets_the_rule_right_before_it() -> None:
    [message] = await DisputeContributor().contribute(ctx("you are wrong, it is Liverpool"))
    said = message.content.lower()
    assert message.role is Role.SYSTEM
    assert "you're right" in said and "apolog" in said
    assert "search" in said


async def test_with_nothing_said_yet_there_is_nothing_to_dispute() -> None:
    assert await DisputeContributor().contribute(ctx("you are wrong", history=())) == []


def test_it_sits_between_the_history_and_the_message() -> None:
    orders = {c.name: c.order for c in build_contributors()}
    assert orders["history"] < orders["dispute"] < orders["user_message"]
