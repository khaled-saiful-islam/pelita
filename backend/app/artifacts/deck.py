"""Assembling slides into one document.

A deck is still one self-contained HTML file — the same currency as a poster,
so sharing, downloading, printing and the panel all work unchanged. The only
difference is that it has several `<section>` elements instead of one canvas.

Kept apart from the kind because assembling is string work with rules of its
own, and because the panel needs the same shell to show a single slide while
the rest are still being written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# `<section class="slide …">` … `</section>`, non-greedy so a deck splits back
# into the pieces it was assembled from.
_SECTION = re.compile(r"<section\b[^>]*class=\"[^\"]*\bslide\b[^\"]*\"[\s\S]*?</section>")


@dataclass(frozen=True, slots=True)
class Deck:
    title: str
    css: str
    width: int
    height: int
    fonts: tuple[str, ...] = ()


def font_link(families: tuple[str, ...]) -> str:
    """The one stylesheet the sandbox allows."""
    wanted = [family.strip().replace(" ", "+") for family in families if family.strip()]
    if not wanted:
        return ""
    query = "&".join(f"family={name}:wght@300;400;500;600;700;900" for name in wanted)
    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link href="https://fonts.googleapis.com/css2?{query}&display=swap" rel="stylesheet">'
    )


def shell(deck: Deck) -> str:
    """The rules every deck needs, whatever the design on top of them says.

    Written here rather than asked for, because they are not design decisions:
    a slide that is not the size it claims, or a deck that prints four to a
    page, is broken in a way no stylesheet should be able to cause.
    """
    return (
        "* { box-sizing: border-box; }\n"
        "html, body { margin: 0; padding: 0; background: #0b0b0c; }\n"
        "body { counter-reset: slide; }\n"
        f".slide {{ width: {deck.width}px; height: {deck.height}px; overflow: hidden; "
        "position: relative; display: flex; flex-direction: column; "
        "counter-increment: slide; margin: 0 auto; }\n"
        f"@page {{ size: {deck.width}px {deck.height}px; margin: 0; }}\n"
        "@media print {\n"
        "  .slide { break-after: page; page-break-after: always; margin: 0; }\n"
        "  .slide:last-child { break-after: auto; page-break-after: auto; }\n"
        "  html, body { background: none; }\n"
        "  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }\n"
        "}\n"
        ".speaker-notes { display: none; }\n"
    )


def size_guard(deck: Deck) -> str:
    """The slide's size, restated after the design has had its say.

    The shell comes first so the design can build on it — padding, ground,
    layout. But a slide that is not the size it claims is broken in a way no
    stylesheet should be able to cause, and a deck whose slides are not 16:9
    is not a deck anybody can present. So the size is asserted again at the
    end, where a later rule of equal specificity simply wins, and no
    `!important` is needed to say it.

    `aspect-ratio` is cleared rather than left alone: an explicit width and
    height already beat it, so a design that declared `4 / 3` renders 16:9
    anyway — but its computed style would still read `4 / 3`, which is a lie
    to anyone debugging the deck later.
    """
    return (
        f".slide {{ width: {deck.width}px; height: {deck.height}px; "
        "aspect-ratio: auto; overflow: hidden; box-sizing: border-box; }\n"
    )


def document(deck: Deck, sections: list[str]) -> str:
    """The whole deck, ready to share, print or put in a frame."""
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        f"<title>{_escape(deck.title)}</title>\n"
        f"{font_link(deck.fonts)}\n"
        f"<style>\n{shell(deck)}\n{deck.css}\n{size_guard(deck)}</style>\n"
        "</head>\n<body>\n"
        + "\n".join(sections)
        + "\n</body>\n</html>"
    )


def one_slide(deck: Deck, section: str) -> str:
    """A single slide as its own document, for showing it before the rest
    exist. The same shell and the same stylesheet, so what is on screen while
    a deck is being built is what will be in the deck."""
    return document(deck, [section])


def sections_of(html: str) -> list[str]:
    """The slides in a finished deck, in order."""
    return _SECTION.findall(html)


def replace_sections(html: str, sections: list[str]) -> str:
    """Put a different set of slides into the same deck.

    Everything outside the sections — the head, the stylesheet, the fonts —
    is untouched, which is what lets a slide be added or removed without
    redesigning the deck around it.
    """
    found = list(_SECTION.finditer(html))
    if not found:
        return html
    return html[: found[0].start()] + "\n".join(sections) + html[found[-1].end() :]


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").strip()
        or "Deck"
    )
