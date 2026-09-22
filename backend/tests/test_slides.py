"""Planning and assembling a deck."""

from __future__ import annotations

import pytest

from app.artifacts.base import Brief
from app.artifacts.deck import Deck, document, one_slide, replace_sections, sections_of
from app.artifacts.slide_prompts import DEFAULT_SLIDES, MAX_SLIDES, MIN_SLIDES
from app.artifacts.slides import wanted_slides

DECK = Deck(title="Kopi", css=".slide--title{color:red}", width=1600, height=900,
            fonts=("Lora", "Work Sans"))
SECTIONS = [
    '<section class="slide slide--title"><h1>One</h1></section>',
    '<section class="slide slide--points"><h2>Two</h2></section>',
]


def brief(text: str = "", *, count: int = 0, title: str = "A talk") -> Brief:
    return Brief(kind="slides", title=title, brief=text, count=count)


# --- how many slides ----------------------------------------------------


def test_the_number_the_person_gave_wins() -> None:
    """A number said in passing is one the chat model will paraphrase away
    while still repeating it back. It announced an eight-slide deck and made
    ten, which is how this field came to exist."""
    assert wanted_slides(brief("a deck about kopi", count=8)) == 8


def test_a_number_in_the_brief_is_the_fallback() -> None:
    assert wanted_slides(brief("make me a 6 slide deck about kopi")) == 6
    assert wanted_slides(brief("a 12 page deck")) == 12


def test_no_number_means_ten() -> None:
    assert wanted_slides(brief("a deck about kopi")) == DEFAULT_SLIDES


@pytest.mark.parametrize(("asked", "given"), [(1, MIN_SLIDES), (99, MAX_SLIDES)])
def test_a_silly_number_is_brought_back_into_range(asked: int, given: int) -> None:
    assert wanted_slides(brief("x", count=asked)) == given


# --- assembling ---------------------------------------------------------


def test_a_deck_is_one_document_with_its_slides_in_it() -> None:
    html = document(DECK, SECTIONS)

    assert html.startswith("<!DOCTYPE html>")
    assert "<title>Kopi</title>" in html
    assert ".slide--title{color:red}" in html
    assert len(sections_of(html)) == 2


def test_every_slide_is_the_size_it_claims() -> None:
    html = document(DECK, SECTIONS)
    assert "width: 1600px" in html
    assert "height: 900px" in html


def test_a_deck_prints_one_slide_to_a_page() -> None:
    html = document(DECK, SECTIONS)
    assert "@page { size: 1600px 900px; margin: 0; }" in html
    assert "page-break-after: always" in html


def test_speaker_notes_are_in_the_file_and_not_on_the_slide() -> None:
    html = document(DECK, SECTIONS)
    assert ".speaker-notes { display: none; }" in html


def test_one_slide_carries_the_whole_look() -> None:
    """A slide shown before the rest exist has to look like the deck it will
    be part of, not like a fragment."""
    alone = one_slide(DECK, SECTIONS[0])
    assert ".slide--title{color:red}" in alone
    assert len(sections_of(alone)) == 1


def test_slides_can_be_swapped_without_touching_the_design() -> None:
    """What lets a slide be added or removed without redesigning the deck."""
    html = document(DECK, SECTIONS)
    changed = replace_sections(html, [SECTIONS[0]])

    assert len(sections_of(changed)) == 1
    assert ".slide--title{color:red}" in changed
    assert "<title>Kopi</title>" in changed


def test_a_title_with_markup_in_it_cannot_escape() -> None:
    sneaky = Deck(title="<script>x</script>", css="", width=1600, height=900)
    assert "<script>" not in document(sneaky, [])


def test_the_fonts_are_asked_for_from_the_one_allowed_host() -> None:
    html = document(DECK, SECTIONS)
    assert "fonts.googleapis.com" in html
    assert "family=Lora" in html
    assert "family=Work+Sans" in html
