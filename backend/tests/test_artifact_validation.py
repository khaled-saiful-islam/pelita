"""What a document has to get right before anyone sees it.

Each check gets a document that fails it and one that passes, because a
validator nobody has watched fail is a validator that might be checking
nothing.
"""

from __future__ import annotations

import pytest

from app.artifacts.base import DesignSpec, SandboxPolicy
from app.artifacts.validate import check, repair_request

SPEC = DesignSpec(movement="Test", width=794, height=1123)
STATIC = SandboxPolicy(scripts=False)

GOOD = """<!DOCTYPE html>
<html><head><style>
:root { --ground: #101010; }
.canvas { width: 794px; height: 1123px; background: var(--ground); }
h1 { text-wrap: balance; }
</style>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Lora">
</head><body><div class="canvas"><h1>Hello</h1></div></body></html>"""


def failures(document: str, *, spec: DesignSpec = SPEC) -> list[str]:
    return [f.rule for f in check(document, spec=spec, sandbox=STATIC, max_bytes=100_000)]


def test_a_good_document_has_nothing_wrong_with_it() -> None:
    assert failures(GOOD) == []


def test_a_document_cut_off_mid_stream_is_caught() -> None:
    """The commonest real failure: the model hit its token ceiling."""
    assert "The document is cut off" in failures(GOOD[: len(GOOD) // 2])


def test_a_document_with_no_canvas_is_caught() -> None:
    assert 'There is no element with class "canvas"' in failures(
        GOOD.replace('class="canvas"', 'class="wrapper"')
    )


def test_a_script_is_caught_because_the_frame_would_refuse_it_silently() -> None:
    """The sandbox refuses without saying so. A poster depending on a script it
    cannot run just looks broken, with nothing anywhere explaining why."""
    assert "The document contains a <script>" in failures(
        GOOD.replace("</body>", "<script>alert(1)</script></body>")
    )


def test_an_inline_event_handler_is_caught() -> None:
    assert "The document has inline event handlers" in failures(
        GOOD.replace('<div class="canvas">', '<div class="canvas" onclick="go()">')
    )


def test_an_image_tag_is_caught() -> None:
    assert "The document contains an <img>" in failures(
        GOOD.replace("<h1>Hello</h1>", '<img src="https://example.test/a.jpg">')
    )


def test_a_stylesheet_loading_a_picture_is_caught() -> None:
    assert "A stylesheet loads an external image" in failures(
        GOOD.replace("background: var(--ground);", "background: url(https://a.test/b.png);")
    )


def test_a_data_uri_background_is_not_an_external_image() -> None:
    """Drawn, not fetched. An inline SVG data URI is the model's own work."""
    drawn = "background: url(data:image/svg+xml,%3Csvg/%3E);"
    assert failures(GOOD.replace("background: var(--ground);", drawn)) == []


def test_an_invented_link_is_caught() -> None:
    """A model asked for a poster reliably invents a plausible website for the
    venue. It is the one failure a person cannot see is wrong."""
    assert "The document links to a URL nobody supplied" in failures(
        GOOD.replace("<h1>Hello</h1>", '<a href="https://barkopi.example">barkopi.example</a>')
    )


def test_the_font_host_is_not_an_invented_link() -> None:
    assert "The document links to a URL nobody supplied" not in failures(GOOD)


def test_a_nowrap_heading_is_caught() -> None:
    assert "A heading is set to white-space: nowrap" in failures(
        GOOD.replace("h1 { text-wrap: balance; }", "h1 { white-space: nowrap; }")
    )


def test_a_canvas_of_the_wrong_size_is_caught() -> None:
    assert "The canvas is not the size it was given" in failures(
        GOOD, spec=DesignSpec(movement="Test", width=1080, height=1080)
    )


def test_a_canvas_with_no_background_is_caught() -> None:
    """It inherits whatever is behind it, so half the time it is unreadable."""
    assert "The canvas sets no background" in failures(
        GOOD.replace("background: var(--ground);", "")
    )


def test_a_runaway_document_is_caught() -> None:
    padded = GOOD.replace("<h1>Hello</h1>", "<h1>" + "x" * 200_000 + "</h1>")
    assert "The document is too large" in failures(padded)


@pytest.mark.parametrize("attribute", ["width", "height"])
def test_a_spec_with_no_size_does_not_demand_one(attribute: str) -> None:
    """Size is checked against what the direction chose. When it chose nothing,
    there is nothing to check against."""
    assert "The canvas is not the size it was given" not in failures(
        GOOD, spec=DesignSpec(movement="Test")
    )


# --- what the model is told -------------------------------------------


def test_the_repair_names_every_problem_and_the_document() -> None:
    findings = check(
        GOOD.replace("</body>", "<script>x</script></body>"),
        spec=SPEC,
        sandbox=STATIC,
        max_bytes=100_000,
    )
    request = repair_request("<!DOCTYPE html>...", findings)

    assert "<script>" in request
    assert "Change nothing else" in request
    assert "<!DOCTYPE html>..." in request
