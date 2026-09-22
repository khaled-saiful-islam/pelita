"""Changing the words without asking a model."""

from __future__ import annotations

from app.artifacts.text_edit import apply_text, readable_text

POSTER = (
    "<!DOCTYPE html><html><head><title>Jazz night</title>"
    "<style>.canvas{width:794px;content:'x'}</style></head>"
    '<body><div class="canvas">'
    "<h1>Friday night jazz</h1>\n  <p>RM35 at the door</p>"
    "<span></span>"
    "</div></body></html>"
)


def test_the_words_are_the_words_a_person_can_see() -> None:
    assert readable_text(POSTER) == ["Friday night jazz", "RM35 at the door"]


def test_a_stylesheet_is_not_words() -> None:
    """Letting CSS be edited here is how a colour becomes `#ff0000;}`."""
    assert "794px" not in " ".join(readable_text(POSTER))


def test_changing_one_run_leaves_everything_else_byte_for_byte() -> None:
    edited = apply_text(POSTER, {1: "RM40 at the door"})

    assert "RM40 at the door" in edited
    assert "Friday night jazz" in edited
    assert ".canvas{width:794px;content:'x'}" in edited
    assert edited.count("<div") == POSTER.count("<div")


def test_the_layout_around_the_words_survives() -> None:
    """Whitespace padding a run is layout, not words. Eating it lets an edit
    silently reflow the document it is in."""
    padded = POSTER.replace("<p>RM35 at the door</p>", "<p>\n    RM35 at the door\n  </p>")
    edited = apply_text(padded, {1: "RM40"})

    assert "<p>\n    RM40\n  </p>" in edited
    # And whitespace that stands between two tags is left alone entirely.
    assert "</h1>\n  <p>" in edited


def test_text_is_escaped_on_the_way_in() -> None:
    edited = apply_text(POSTER, {0: "Jazz & <script>alert(1)</script>"})
    assert "<script>" not in edited
    assert "&lt;script&gt;" in edited


def test_a_run_nobody_recognises_is_ignored_rather_than_fatal() -> None:
    """The document may have been edited by somebody else in the meantime, and
    losing one correction beats losing all of them."""
    edited = apply_text(POSTER, {0: "Saturday night jazz", 99: "nowhere"})
    assert "Saturday night jazz" in edited


def test_a_very_long_run_is_cut_rather_than_stored() -> None:
    edited = apply_text(POSTER, {0: "x" * 5000})
    assert len(edited) < len(POSTER) + 2100


def test_no_changes_is_the_same_document() -> None:
    assert apply_text(POSTER, {}) == POSTER


def test_the_numbering_survives_a_round_trip() -> None:
    """The browser walks the same document in the same order, so what was
    edited against is what is applied."""
    edited = apply_text(POSTER, {0: "Sunday jazz"})
    assert readable_text(edited) == ["Sunday jazz", "RM35 at the door"]


def test_the_title_is_not_a_word_on_the_poster() -> None:
    """The browser numbers what it can see, walking from <body>. Counting the
    <title> here shifts every number by one, and an edit lands on the run next
    to the one somebody meant.

    Found in a browser: editing the fee on a banner rewrote "RM" instead.
    """
    assert "Jazz night" not in readable_text(POSTER)
    assert readable_text(POSTER)[0] == "Friday night jazz"

    edited = apply_text(POSTER, {0: "Saturday night jazz"})
    assert "<title>Jazz night</title>" in edited
    assert "Saturday night jazz" in edited


def test_a_fragment_with_no_body_tag_is_all_body() -> None:
    assert readable_text("<div><h1>Hello</h1></div>") == ["Hello"]


def test_entities_read_as_the_characters_a_person_sees() -> None:
    """`&nbsp;` is a space on the poster. A caller comparing its own reading
    against this one should not have to know how the document spells it."""
    document = POSTER.replace("RM35 at the door", "RM35 &nbsp;/&nbsp; at the door")
    assert readable_text(document)[1] == "RM35 \xa0/\xa0 at the door"


def test_the_round_trip_through_an_entity_is_symmetric() -> None:
    document = POSTER.replace("RM35 at the door", "Tea &amp; kopi")
    assert readable_text(document)[1] == "Tea & kopi"

    edited = apply_text(document, {1: "Tea & kopi-o"})
    assert "Tea &amp; kopi-o" in edited
    assert readable_text(edited)[1] == "Tea & kopi-o"
