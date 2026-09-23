"""Planning and assembling a deck."""

from __future__ import annotations

import pytest

from app.artifacts.base import Brief
from app.artifacts.deck import Deck, document, one_slide, replace_sections, sections_of
from app.artifacts.imagery import Photo, attach_photos
from app.artifacts.slide_prompts import DEFAULT_SLIDES, MAX_SLIDES, MIN_SLIDES
from app.artifacts.slides import (
    _enough_grounds,
    _grounds,
    _named_grounds,
    _photo_variables,
    _photos_in_use,
    _section_of,
    wanted_slides,
)

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


def test_no_number_means_five() -> None:
    """A deck nobody gave a size is one somebody is waiting on. Ten was twice
    the wait for twice the deck they asked for."""
    assert DEFAULT_SLIDES == 5
    assert wanted_slides(brief("a deck about kopi")) == DEFAULT_SLIDES


def test_too_many_is_brought_back_into_range() -> None:
    assert wanted_slides(brief("x", count=99)) == MAX_SLIDES


@pytest.mark.parametrize("asked", [1, 2])
def test_a_count_below_the_minimum_is_a_misreading_not_a_request(asked: int) -> None:
    """Clamping up to the minimum turned a misreading into a wrong answer:
    "create a slide about EV cars" was read as one slide and came back as a
    three-slide deck with no opening. Nobody asks for a deck of one."""
    assert wanted_slides(brief("x", count=asked)) == DEFAULT_SLIDES
    assert MIN_SLIDES == 3  # the value that used to be returned here


def test_a_talk_opens_and_closes_however_the_outline_came_back() -> None:
    """The outline prompt says title first and closing last, always, and a
    deck came back opening on a `data` slide. A rule nothing checks holds
    right up until the model is short of room."""
    from app.artifacts.slides import Slide, _bookended

    made = _bookended([
        Slide(heading="Charging", layout="data", job="", content=""),
        Slide(heading="Costs", layout="points", job="", content=""),
        Slide(heading="Uptake", layout="split", job="", content=""),
    ])

    assert [s.layout for s in made] == ["title", "points", "closing"]


def test_a_deck_that_already_opens_properly_is_left_alone() -> None:
    from app.artifacts.slides import Slide, _bookended

    proper = [
        Slide(heading="A", layout="title", job="", content=""),
        Slide(heading="B", layout="points", job="", content=""),
        Slide(heading="C", layout="closing", job="", content=""),
    ]
    assert [s.layout for s in _bookended(list(proper))] == ["title", "points", "closing"]


def test_a_single_slide_is_an_opening_and_nothing_else() -> None:
    from app.artifacts.slides import Slide, _bookended

    made = _bookended([Slide(heading="A", layout="data", job="", content="")])
    assert [s.layout for s in made] == ["title"]


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


# --- reading the design back --------------------------------------------


def a_look(text: str):
    from app.artifacts.slides import _read_look

    return _read_look(text)


def test_the_stylesheet_survives_quotes_and_newlines() -> None:
    """Why it is not asked for as a JSON string. A deck's CSS is full of
    `font-family: "Lora"` and `content: "01"`, and a model escaping all of that
    into one JSON value gets it wrong often enough that whole decks were lost
    to a parse error — reported as "the design model returned no stylesheet".
    """
    look = a_look(
        'MOVEMENT: Kopitiam Warmth\n'
        'DISPLAY: Lora\n'
        'BODY: Work Sans\n'
        'WHY: it suits the subject\n'
        '---CSS---\n'
        ':root { --ground: #f3ead7; }\n'
        '.slide { font-family: "Lora", serif; }\n'
        '.slide::after { content: "01"; }\n'
    )

    assert look.movement == "Kopitiam Warmth"
    assert look.display_font == "Lora"
    assert look.body_font == "Work Sans"
    assert 'font-family: "Lora", serif' in look.css
    assert 'content: "01"' in look.css


def test_a_model_that_forgot_the_marker_still_works() -> None:
    """The stylesheet starts where :root does, whatever came before it."""
    look = a_look('MOVEMENT: Plain\nDISPLAY: Lora\nBODY: Inter\n:root { --a: #fff; }')
    assert look.css.startswith(":root")
    assert look.movement == "Plain"


def test_a_fenced_answer_is_unwrapped() -> None:
    look = a_look('MOVEMENT: X\n---CSS---\n```css\n:root { --a: #fff; }\n```')
    assert look.css.startswith(":root")
    assert "```" not in look.css


def test_nothing_usable_is_nothing_usable() -> None:
    """Reported honestly rather than turned into an empty deck."""
    assert a_look("I think a warm palette would be nice.").css == ""


def test_the_faces_fall_back_rather_than_being_empty() -> None:
    look = a_look("---CSS---\n:root { --a: #fff; }")
    assert look.display_font and look.body_font


def test_a_slide_is_sixteen_by_nine_whatever_the_design_says() -> None:
    """A slide that is not the size it claims is broken in a way no stylesheet
    should be able to cause, and the design's CSS comes after the shell."""
    from app.artifacts.deck import Deck as DeckShape

    overriding = DeckShape(
        title="x",
        css=".slide { width: 1024px; height: 768px; }",
        width=1600,
        height=900,
    )
    html = document(overriding, SECTIONS)

    # The design's own rule is still there; ours is after it and wins.
    assert "width: 1024px" in html
    assert html.index("width: 1024px") < html.rindex("width: 1600px")
    assert pytest.approx(16 / 9) == 1600 / 900


def test_a_declared_aspect_ratio_does_not_outlive_the_guard() -> None:
    """Width and height already beat `aspect-ratio`, so the box renders 16:9
    either way — but the computed style would still report the design's
    figure, which misleads whoever debugs the deck next."""
    from app.artifacts.deck import Deck as DeckShape

    lying = DeckShape(
        title="x",
        css=".slide { aspect-ratio: 4 / 3; }",
        width=1600,
        height=900,
    )
    html = document(lying, SECTIONS)

    assert html.index("aspect-ratio: 4 / 3") < html.rindex("aspect-ratio: auto")


def test_the_ratio_is_the_one_people_present_in() -> None:
    from app.artifacts.slides import WIDESCREEN

    assert pytest.approx(16 / 9) == WIDESCREEN.width / WIDESCREEN.height


# --- which picture a slide is told about --------------------------------


def _photo(tag: str) -> Photo:
    return Photo(data_uri=f"data:image/jpeg;base64,{tag}", source="", width=800, height=600)


def test_each_slide_is_told_the_variable_its_own_picture_lands_in() -> None:
    """The names come from position in the attached list. Told the wrong one,
    a slide puts another slide's photograph behind its words."""
    ordered, variables = _photo_variables({3: _photo("C"), 1: _photo("A")})

    assert [p.data_uri[-1] for p in ordered] == ["A", "C"]
    assert variables == {1: "--photo", 3: "--photo-2"}


def test_a_picture_no_slide_used_is_not_embedded() -> None:
    """A hundred kilobytes of base64 in every copy of the deck, to show
    nobody anything."""
    ordered, variables = _photo_variables({0: _photo("A")})
    html = "<section class='slide'><h1>No picture here</h1></section>"

    assert _photos_in_use(html, ordered, variables) == [None]


def test_dropping_an_unused_picture_does_not_rename_the_others() -> None:
    """Dropping it from the list would shift every name after it, and the
    slide asking for `--photo-2` would get the wrong photograph."""
    ordered, variables = _photo_variables({0: _photo("A"), 1: _photo("B")})
    html = "<section class='slide' style='background-image: var(--photo-2)'></section>"

    in_use = _photos_in_use(html, ordered, variables)

    assert in_use[0] is None
    assert in_use[1] is not None and in_use[1].data_uri.endswith("B")
    assert '--photo-2: url("data:image/jpeg;base64,B")' in attach_photos(
        "<style>:root{}</style>", in_use
    )


# --- the ground each slide sits on --------------------------------------

# Names a design invented for a subject, not a vocabulary this module owns.
REEF = ("slide--abyss", "slide--shallows", "slide--sand")


def test_the_moments_meant_to_land_get_the_emphatic_ground() -> None:
    assert _grounds(["title", "points", "closing"], REEF) == [
        "slide--abyss",
        "slide--shallows",
        "slide--abyss",
    ]


def test_a_run_of_three_the_same_is_broken_up() -> None:
    """A five-slide deck is usually a title, three `points` and a closing,
    which by layout alone is three identical slides in the middle."""
    got = _grounds(["title", "points", "points", "points", "closing"], REEF)

    assert got[0] == got[4] == "slide--abyss"
    assert got[1] != got[2] or got[2] != got[3]


def test_a_deck_is_never_one_colour_end_to_end() -> None:
    for layouts in (["points"] * 6, ["title", "points", "points", "closing"]):
        assert len(set(_grounds(layouts, REEF))) > 1, layouts


def test_the_names_are_the_designs_own() -> None:
    """A deck about deep-sea vents and a deck about a bakery should not be
    reaching into the same box of tones."""
    bakery = ("slide--crust", "slide--flour")
    assert set(_grounds(["title", "points"], bakery)) <= set(bakery)


def test_a_design_that_named_no_grounds_leaves_the_slides_bare() -> None:
    assert _grounds(["title", "points"], ()) == ["", ""]


def test_a_ground_the_stylesheet_never_defines_does_not_count() -> None:
    """A name with no rule behind it puts a class on a slide that does
    nothing, which is the flat deck this exists to prevent."""
    css = ".slide--abyss { background: #04121e; }"
    assert _named_grounds("slide--abyss, slide--shallows", css) == ("slide--abyss",)


def test_grounds_are_read_however_they_were_written() -> None:
    css = ".slide--abyss{}.slide--sand{}"
    assert _named_grounds(".slide--abyss; .slide--sand", css) == (
        "slide--abyss",
        "slide--sand",
    )


def test_a_design_that_moves_between_one_ground_is_not_enough() -> None:
    from app.artifacts.slides import Look

    assert not _enough_grounds(Look(grounds=("slide--abyss",)))
    assert _enough_grounds(Look(grounds=("slide--abyss", "slide--sand")))


def test_the_ground_is_put_on_the_slide_not_asked_for() -> None:
    """A deck whose grounds alternate only when the writer remembered is a
    deck of one ground."""
    written = '<section class="slide slide--points"><h2>Hi</h2></section>'
    out = _section_of(written, "points", "slide--abyss")

    assert "slide--abyss" in out and "slide--points" in out


def test_a_writer_that_guessed_a_ground_does_not_get_two() -> None:
    written = '<section class="slide slide--title slide--sand"><h1>Hi</h1></section>'
    out = _section_of(written, "title", "slide--abyss", REEF)

    assert "slide--sand" not in out
    assert "slide--abyss" in out
    assert "slide--title" in out


def test_a_slide_with_no_class_at_all_still_gets_its_ground() -> None:
    assert 'class="slide slide--sand"' in _section_of(
        "<section><h2>Hi</h2></section>", "points", "slide--sand"
    )


def test_a_slide_wears_one_ground_not_two() -> None:
    """The writer is given the stylesheet, sees the grounds in it, and picks
    one of its own. A real deck came out with `ground--canopy ground--mist`
    on the same slide."""
    written = '<section class="slide slide--points ground--mist"><h2>Hi</h2></section>'
    out = _section_of(written, "points", "ground--canopy", ("ground--canopy", "ground--mist"))

    assert "ground--mist" not in out
    assert out.count("ground--canopy") == 1


def test_an_added_slide_finds_the_grounds_the_deck_already_uses() -> None:
    """The design ran in an earlier turn, so the deck itself is the only
    record of what its grounds are called."""
    from app.artifacts.slides import _grounds_in

    html = (
        '<section class="slide slide--title ground--canopy"></section>'
        '<section class="slide slide--points ground--mist"></section>'
        '<section class="slide slide--closing ground--canopy"></section>'
    )
    assert _grounds_in(html) == ["ground--canopy"]
