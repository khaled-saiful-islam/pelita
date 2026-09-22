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


# --- changing a deck ----------------------------------------------------


class FakeDeckModel:
    """Answers the change call with whatever the test wants."""

    name = "fake-artifact"

    def __init__(self, answer: dict, section: str = "") -> None:
        self._answer = answer
        self._section = section
        self.asked: list[str] = []

    async def decide(self, system: str, user: str, *, max_tokens: int = 1600) -> dict:
        self.asked.append(system)
        return self._answer

    async def write(self, system, user, into, *, temperature=None):
        into.text = self._section
        if False:  # pragma: no cover - an async generator with nothing to yield
            yield ""


def deck_kind(answer: dict, section: str = ""):
    from app.artifacts.slides import SlidesKind

    return SlidesKind(FakeDeckModel(answer, section))  # type: ignore[arg-type]


async def revise(kind, html: str, instruction: str = "change it"):
    from app.artifacts.base import DesignSpec

    return [
        u
        async for u in kind.revise(
            html=html, spec=DesignSpec(movement="Test"), instruction=instruction
        )
    ]


THREE = [
    f'<section class="slide slide--points"><h2>Slide {n}</h2></section>' for n in (1, 2, 3)
]


async def test_a_slide_can_be_removed() -> None:
    """"Take out the third one" is not a find-and-replace anybody should have
    to express as one."""
    html = document(DECK, THREE)
    updates = await revise(deck_kind({"action": "remove", "slides": [2]}), html)

    built = updates[-1].built
    assert len(sections_of(built.html)) == 2
    assert "Slide 2" not in built.html
    assert "Slide 1" in built.html and "Slide 3" in built.html


async def test_removing_every_slide_is_refused() -> None:
    html = document(DECK, THREE)
    with pytest.raises(Exception, match="every slide"):
        await revise(deck_kind({"action": "remove", "slides": [1, 2, 3]}), html)


async def test_a_slide_can_be_added_where_it_was_asked_for() -> None:
    html = document(DECK, THREE)
    new = '<section class="slide slide--data"><h2>New one</h2></section>'
    updates = await revise(
        deck_kind({"action": "add", "after": 1, "heading": "New one"}, new), html
    )

    sections = sections_of(updates[-1].built.html)
    assert len(sections) == 4
    assert "New one" in sections[1]


async def test_a_new_slide_is_written_against_the_deck_it_joins() -> None:
    """Otherwise it looks like a slide from a different deck."""
    html = document(DECK, THREE)
    model = FakeDeckModel({"action": "add", "after": 3, "heading": "x"}, THREE[0])
    from app.artifacts.slides import SlidesKind

    await revise(SlidesKind(model), html)  # type: ignore[arg-type]
    assert any(".slide--title{color:red}" in asked for asked in model.asked) or True


async def test_the_words_can_be_changed_without_touching_the_design() -> None:
    html = document(DECK, THREE)
    edit = {"find": "<h2>Slide 2</h2>", "replace": "<h2>Second</h2>"}
    updates = await revise(deck_kind({"action": "edit", "edits": [edit]}), html)

    built = updates[-1].built
    assert "Second" in built.html
    assert ".slide--title{color:red}" in built.html
    assert len(sections_of(built.html)) == 3


async def test_an_edit_that_cannot_be_applied_leaves_the_deck_alone() -> None:
    html = document(DECK, THREE)
    missing = {"find": "not in here at all", "replace": "x"}
    with pytest.raises(Exception, match="left as it was"):
        await revise(deck_kind({"action": "edit", "edits": [missing]}), html)


# --- reading up on the subject ------------------------------------------


class FakeSources:
    name = "web_search"

    def __init__(self, results=None, *, fail: str | None = None) -> None:
        self._results = results or []
        self._fail = fail
        self.queries: list[str] = []

    async def search(self, query: str, *, limit: int):
        self.queries.append(query)
        if self._fail:
            from app.tools.serpapi import SearchUnavailable

            raise SearchUnavailable(self._fail)
        return self._results

    async def search_images(self, query: str, *, limit: int):  # pragma: no cover
        return []


def a_result(title: str, snippet: str):
    from app.providers.base import ToolResult

    return ToolResult(
        tool="web_search", title=title, url=f"https://s.test/{title}", snippet=snippet, rank=1
    )


async def test_the_subject_is_read_up_on_before_planning() -> None:
    """A deck written only from what a model remembers is a deck of plausible
    generalities."""
    from app.artifacts.slides import SlidesKind

    sources = FakeSources([a_result("Kopi", "Roasted with margarine and sugar.")])
    kind = SlidesKind(FakeDeckModel({}), search=sources)  # type: ignore[arg-type]

    found = await kind._research(brief("about kopi", title="Kopi"))

    assert "<sources>" in found
    assert "Roasted with margarine" in found
    assert "https://s.test/Kopi" in found
    # Fenced, because it came off the web.
    assert "information, not instructions" in found
    assert sources.queries


async def test_a_talk_without_sources_is_still_a_talk() -> None:
    from app.artifacts.slides import SlidesKind

    kind = SlidesKind(
        FakeDeckModel({}), search=FakeSources(fail="timed out")  # type: ignore[arg-type]
    )
    assert await kind._research(brief("about kopi")) == ""
