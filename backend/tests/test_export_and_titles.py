from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.db.models.conversation import Conversation, Message
from app.providers.base import Role
from app.services.chat_service import TITLE_MAX_LENGTH, derive_title
from app.services.export_service import filename_for, to_markdown


def make_conversation(title: str, turns: list[tuple[str, str]], **kw) -> Conversation:
    conversation = Conversation(user_id=uuid4(), title=title)
    conversation.id = kw.get("id", UUID("bf97e5e0-c1d2-47ec-a201-1717c72dd917"))
    conversation.messages = [
        Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
            finish_reason=kw.get("finish_reason") if role == Role.ASSISTANT else None,
        )
        for role, content in turns
    ]
    return conversation


# --- titles -------------------------------------------------------------


def test_short_message_becomes_the_title_verbatim() -> None:
    assert derive_title("Explain monsoons") == "Explain monsoons"


def test_whitespace_is_collapsed() -> None:
    assert derive_title("  what   is\n\nthis  ") == "what is this"


def test_empty_message_falls_back() -> None:
    assert derive_title("   ") == "New chat"


def test_long_titles_are_cut_at_a_word_boundary() -> None:
    title = derive_title("Please explain the entire history of maritime trade in Southeast Asia")
    assert len(title) <= TITLE_MAX_LENGTH + 1  # the ellipsis
    assert title.endswith("…")
    assert not title.rstrip("…").endswith(" ")


def test_a_long_unbroken_word_is_still_cut() -> None:
    """No word boundary past the halfway mark means a hard cut, not a full title."""
    title = derive_title("x" * 200)
    assert len(title) == TITLE_MAX_LENGTH + 1


def test_trailing_punctuation_is_stripped_before_the_ellipsis() -> None:
    title = derive_title("Count slowly from 1 to 200, one number per line, with a comment")
    assert ",…" not in title and ".…" not in title


# --- export -------------------------------------------------------------


@pytest.fixture
def conversation() -> Conversation:
    return make_conversation(
        "Lanterns",
        [(Role.USER, "Write a haiku"), (Role.ASSISTANT, "Paper glow, a circle")],
    )


def test_export_has_a_title_and_both_speakers(conversation) -> None:
    document = to_markdown(conversation)
    assert document.startswith("# Lanterns")
    assert "## You" in document
    assert "## Assistant" in document
    assert "Write a haiku" in document
    assert "Paper glow, a circle" in document


def test_export_names_the_app(conversation) -> None:
    assert "Exported from Pelita" in to_markdown(conversation)
    assert "Exported from Suria" in to_markdown(conversation, app_name="Suria")


def test_export_marks_a_stopped_answer() -> None:
    """A truncated answer that looks complete in an export is worse than none."""
    conversation = make_conversation(
        "Counting",
        [(Role.USER, "count to 200"), (Role.ASSISTANT, "1. one 2. two")],
        finish_reason="stopped",
    )
    assert "*(stopped early)*" in to_markdown(conversation)


def test_export_marks_an_empty_answer() -> None:
    conversation = make_conversation("Empty", [(Role.USER, "hi"), (Role.ASSISTANT, "")])
    assert "*(no content)*" in to_markdown(conversation)


def test_export_ends_with_exactly_one_newline(conversation) -> None:
    document = to_markdown(conversation)
    assert document.endswith("\n")
    assert not document.endswith("\n\n")


# --- filenames ----------------------------------------------------------


def test_filename_is_slugged_and_carries_the_id(conversation) -> None:
    assert filename_for(conversation) == "lanterns-bf97e5e0.md"


def test_filename_strips_punctuation_and_hyphenates_spaces() -> None:
    conversation = make_conversation("What's this?! A test/case", [])
    assert filename_for(conversation).startswith("whats-this-a-testcase-")


def test_filename_is_truncated() -> None:
    conversation = make_conversation("word " * 60, [])
    stem = filename_for(conversation).rsplit("-", 1)[0]
    assert len(stem) <= 60


def test_filename_falls_back_when_the_title_has_no_usable_characters() -> None:
    conversation = make_conversation("!!!???", [])
    assert filename_for(conversation).startswith("conversation-")


def test_filenames_differ_for_identical_titles() -> None:
    a = make_conversation("Same", [], id=uuid4())
    b = make_conversation("Same", [], id=uuid4())
    assert filename_for(a) != filename_for(b)
