"""Integration tests against a real Postgres, rolled back after each test."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.db.models.conversation import Conversation, Message
from app.db.models.user import User
from app.providers.base import Role
from app.services.feedback_service import FeedbackService


@pytest.fixture
async def answered(session: AsyncSession, db_user: User) -> tuple[Conversation, Message, Message]:
    conversation = Conversation(user_id=db_user.id, title="Test")
    session.add(conversation)
    await session.flush()

    question = Message(conversation_id=conversation.id, role=Role.USER, content="why?")
    answer = Message(conversation_id=conversation.id, role=Role.ASSISTANT, content="because")
    session.add_all([question, answer])
    await session.flush()
    return conversation, question, answer


async def test_rating_is_stored(session, db_user, answered) -> None:
    _, _, answer = answered
    feedback = await FeedbackService(session).rate(
        user_id=db_user.id, message_id=answer.id, rating="down", reason="wrong"
    )
    assert feedback.rating == "down"
    assert feedback.reason == "wrong"


async def test_rating_again_replaces_rather_than_appends(session, db_user, answered) -> None:
    """The table should say what someone thinks now, not what they clicked."""
    _, _, answer = answered
    service = FeedbackService(session)

    await service.rate(user_id=db_user.id, message_id=answer.id, rating="down", reason="wrong")
    await service.rate(user_id=db_user.id, message_id=answer.id, rating="up")

    stored = await service.for_conversation(
        user_id=db_user.id, conversation_id=answer.conversation_id
    )
    assert len(stored) == 1
    assert stored[answer.id].rating == "up"
    assert stored[answer.id].reason is None


async def test_clearing_removes_the_rating(session, db_user, answered) -> None:
    _, _, answer = answered
    service = FeedbackService(session)
    await service.rate(user_id=db_user.id, message_id=answer.id, rating="up")
    await service.clear(user_id=db_user.id, message_id=answer.id)

    stored = await service.for_conversation(
        user_id=db_user.id, conversation_id=answer.conversation_id
    )
    assert stored == {}


async def test_clearing_a_rating_that_does_not_exist_is_not_an_error(
    session, db_user, answered
) -> None:
    _, _, answer = answered
    await FeedbackService(session).clear(user_id=db_user.id, message_id=answer.id)


async def test_user_messages_cannot_be_rated(session, db_user, answered) -> None:
    _, question, _ = answered
    with pytest.raises(ValidationError, match="assistant messages"):
        await FeedbackService(session).rate(
            user_id=db_user.id, message_id=question.id, rating="up"
        )


async def test_another_users_message_is_not_found(session, answered) -> None:
    """Not 403 — a stranger should not learn that the message exists."""
    _, _, answer = answered
    with pytest.raises(NotFoundError):
        await FeedbackService(session).rate(
            user_id=uuid4(), message_id=answer.id, rating="up"
        )


async def test_unknown_message_is_not_found(session, db_user) -> None:
    with pytest.raises(NotFoundError):
        await FeedbackService(session).rate(
            user_id=db_user.id, message_id=uuid4(), rating="up"
        )


@pytest.mark.parametrize("rating", ["sideways", "", "UP", "1"])
async def test_invalid_ratings_are_rejected(session, db_user, answered, rating) -> None:
    _, _, answer = answered
    with pytest.raises(ValidationError, match="'up' or 'down'"):
        await FeedbackService(session).rate(
            user_id=db_user.id, message_id=answer.id, rating=rating
        )


async def test_a_blank_reason_is_stored_as_none(session, db_user, answered) -> None:
    _, _, answer = answered
    feedback = await FeedbackService(session).rate(
        user_id=db_user.id, message_id=answer.id, rating="down", reason="   "
    )
    assert feedback.reason is None


async def test_an_overlong_reason_is_rejected(session, db_user, answered) -> None:
    _, _, answer = answered
    with pytest.raises(ValidationError, match="2000 characters"):
        await FeedbackService(session).rate(
            user_id=db_user.id, message_id=answer.id, rating="down", reason="x" * 2001
        )
