"""Changing part of a poster instead of writing a new one."""

from __future__ import annotations

from app.artifacts.edits import Edit, apply_edits, read_edits

POSTER = (
    "<!DOCTYPE html><html><head><style>\n"
    ":root { --ground: #101010; --accent: #C8963E; }\n"
    ".canvas{width:794px;height:1123px;background:var(--ground)}\n"
    "</style></head><body><div class='canvas'><h1>Jazz</h1></div></body></html>"
)


def test_one_colour_changes_and_nothing_else_does() -> None:
    """The whole point. Asked to change the background and handed the poster, a
    model returns a different poster; naming the part means everything else is
    untouched by construction rather than by instruction."""
    edited, problems = apply_edits(POSTER, (Edit("--ground: #101010", "--ground: #FFF6E5"),))

    assert problems == ()
    assert "--ground: #FFF6E5" in edited
    assert "--accent: #C8963E" in edited
    assert "<h1>Jazz</h1>" in edited
    assert len(edited) == len(POSTER) + 0  # same shape, different value


def test_text_that_is_not_there_is_reported_not_ignored() -> None:
    """The failure every implementation of this has, and silent in most of
    them: a change that appeared to work and did nothing."""
    edited, problems = apply_edits(POSTER, (Edit("--ground: #ABCDEF", "--ground: #FFF"),))

    assert edited == POSTER
    assert problems and "not in the document" in problems[0]


def test_text_that_appears_twice_is_refused() -> None:
    """The model meant one of them and cannot say which. Changing both is how a
    poster ends up with two identical headings."""
    twice = POSTER.replace("<h1>Jazz</h1>", "<h1>Jazz Night</h1><h2>Jazz Night</h2>")
    edited, problems = apply_edits(twice, (Edit(">Jazz Night<", ">Blues Night<"),))

    assert edited == twice
    assert problems and "ambiguous" in problems[0]


def test_a_find_too_short_to_mean_anything_is_refused() -> None:
    edited, problems = apply_edits(POSTER, (Edit("px", "em"),))
    assert edited == POSTER
    assert problems and "too short" in problems[0]


def test_several_edits_apply_in_order() -> None:
    edited, problems = apply_edits(
        POSTER,
        (
            Edit("--ground: #101010", "--ground: #FFFFFF"),
            Edit("<h1>Jazz</h1>", "<h1>Jazz Night</h1>"),
        ),
    )
    assert problems == ()
    assert "--ground: #FFFFFF" in edited
    assert "Jazz Night" in edited


def test_a_good_edit_still_lands_when_another_one_misses() -> None:
    """Losing one correction beats losing all of them; the miss is reported."""
    edited, problems = apply_edits(
        POSTER,
        (
            Edit("--ground: #101010", "--ground: #FFFFFF"),
            Edit("--nothing: here", "--nothing: there"),
        ),
    )
    assert "--ground: #FFFFFF" in edited
    assert len(problems) == 1


def test_edits_are_read_however_the_model_spells_them() -> None:
    assert read_edits({"edits": [{"find": "a-long-enough-string", "replace": "b"}]}) == (
        Edit("a-long-enough-string", "b"),
    )
    # Some models reach for old/new instead.
    assert read_edits({"edits": [{"old": "a-long-enough-string", "new": "b"}]}) == (
        Edit("a-long-enough-string", "b"),
    )
    assert read_edits({"edits": "not a list"}) == ()
    assert read_edits({}) == ()


def test_a_replacement_may_be_empty_because_removing_is_a_change() -> None:
    edited, problems = apply_edits(POSTER, (Edit("<h1>Jazz</h1>", ""),))
    assert problems == ()
    assert "<h1>" not in edited
