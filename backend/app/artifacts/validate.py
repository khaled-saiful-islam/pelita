"""Checking a document before anyone sees it.

Every check runs in this process against the standard library's HTML parser.
No Node sidecar, no headless browser, no service to be unavailable — which
means these run inside `pytest`, and a rule that cannot be tested is a rule
nobody trusts.

The checks are deliberately about things that are *wrong*, not things that are
ugly. Taste is the prompt's job. This catches a document that will not render,
will render unreadably, or will quietly do something the sandbox is about to
refuse anyway — because a silent refusal is the worst kind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from app.artifacts.base import DesignSpec, SandboxPolicy

# Only the stylesheet host the sandbox allows. Anything else is either blocked
# by the policy or a URL the model invented, and both render as nothing.
ALLOWED_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")

_URL = re.compile(r"https?://([^/\s\"')]+)", re.IGNORECASE)
_CSS_URL = re.compile(r"url\(\s*['\"]?(?!data:)([^)'\"]+)", re.IGNORECASE)
_NOWRAP = re.compile(r"white-space\s*:\s*nowrap", re.IGNORECASE)
# Window units. The poster is looked at in a panel, in its own tab, in a shared
# page and on paper -- four different windows and one correct size.
_WINDOW_UNITS = re.compile(r"\b\d*\.?\d+(vh|vw|vmin|vmax)\b", re.IGNORECASE)
_FIXED = re.compile(r"position\s*:\s*fixed", re.IGNORECASE)
_SCROLLS = re.compile(r"overflow(-[xy])?\s*:\s*(auto|scroll)", re.IGNORECASE)
_CANVAS_RULE = re.compile(r"\.canvas[^{}]*\{([^{}]*)\}", re.IGNORECASE | re.S)
_RULE = re.compile(r"([^{}@]+)\{([^{}]*)\}", re.S)
_HIDDEN = re.compile(r"overflow(-[xy])?\s*:\s*hidden", re.IGNORECASE)
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_BODY_MARGIN = re.compile(r"(html|body)[^{}]*\{[^{}]*margin\s*:\s*0", re.IGNORECASE | re.S)
# A document that stopped mid-token. The last thing a complete one says is a
# closing tag.
_ENDS_CLOSED = re.compile(r"</\s*html\s*>\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Finding:
    """Something wrong, in words a model can act on.

    `rule` is what was broken; `detail` is where. Both go back to the model on
    a repair, so both are written to be read rather than logged.
    """

    rule: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.rule}{f' ({self.detail})' if self.detail else ''}"


class _Reader(HTMLParser):
    """One pass over the document, collecting what the checks ask about."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.scripts = 0
        self.event_attributes: list[str] = []
        self.images = 0
        self.external: list[str] = []
        self.style_text = ""
        self.has_canvas = False
        # Which classes and tags actually hold words. Clipping matters on
        # those and nowhere else: a card clipping a picture to its corners is
        # ordinary CSS, and a heading clipping itself is a bug.
        self.text_classes: set[str] = set()
        self.text_tags: set[str] = set()
        self._in_style = False
        self._open: list[tuple[str, tuple[str, ...]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        if tag == "script":
            self.scripts += 1
        if tag == "style":
            self._in_style = True
        if tag == "img":
            # An embedded picture is one that was found for this poster and
            # travels inside it. A linked one is a URL the model invented.
            source = next((v or "" for k, v in attrs if k == "src"), "")
            if not source.strip().startswith("data:"):
                self.images += 1
        for name, value in attrs:
            if name.startswith("on"):
                self.event_attributes.append(name)
            if name == "class" and value and "canvas" in value.split():
                self.has_canvas = True
            if name in {"src", "href"} and value:
                self._note_url(value)

        classes = tuple(
            (next((v or "" for k, v in attrs if k == "class"), "")).split()
        )
        self._open.append((tag, classes))

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index][0] == tag:
                del self._open[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.style_text += data
            return
        if not data.strip() or not self._open:
            return
        # The element this text sits directly inside, not its ancestors. A
        # wrapper containing a heading does not itself hold words.
        tag, classes = self._open[-1]
        self.text_tags.add(tag)
        self.text_classes.update(classes)

    def _note_url(self, value: str) -> None:
        match = _URL.match(value.strip())
        if match and match.group(1).lower() not in ALLOWED_HOSTS:
            self.external.append(value.strip())


def _structure(reader: _Reader, document: str) -> list[Finding]:
    findings = []
    if not _ENDS_CLOSED.search(document.strip()):
        findings.append(
            Finding("The document is cut off", "it does not end with a closing </html>")
        )
    if "html" not in reader.tags or "body" not in reader.tags:
        findings.append(Finding("The document is not a whole HTML page"))
    if not reader.has_canvas:
        findings.append(
            Finding('There is no element with class "canvas"', "the poster has no root")
        )
    return findings


def _capability(reader: _Reader, sandbox: SandboxPolicy) -> list[Finding]:
    """What the frame is about to refuse anyway.

    Worth failing loudly here, because the sandbox refuses silently: a poster
    that depends on a script it cannot run just looks broken, with nothing
    anywhere saying why.
    """
    findings = []
    if reader.scripts and not sandbox.scripts:
        findings.append(
            Finding(
                "The document contains a <script>",
                "a poster is static and the frame it renders in cannot run one",
            )
        )
    if reader.event_attributes:
        findings.append(
            Finding(
                "The document has inline event handlers",
                ", ".join(sorted(set(reader.event_attributes))[:3]),
            )
        )
    return findings


def _images(reader: _Reader, style: str) -> list[Finding]:
    findings = []
    if reader.images:
        findings.append(
            Finding(
                "The document links to a picture that was not found for it",
                "an invented URL renders as a broken box; only an embedded "
                "image is one that actually exists",
            )
        )
    for url in _CSS_URL.findall(style):
        if not any(host in url for host in ALLOWED_HOSTS):
            findings.append(Finding("A stylesheet loads an external image", url[:80]))
    return findings


def _invented(reader: _Reader) -> list[Finding]:
    """Links to somewhere nobody named.

    A model asked for a poster reliably invents a plausible website for the
    venue. It is the one failure that a person cannot see is wrong.
    """
    return [
        Finding("The document links to a URL nobody supplied", url[:80])
        for url in dict.fromkeys(reader.external)
    ]


_SELECTOR_PART = re.compile(r"[.#]?[A-Za-z][\w-]*")


def _holds_words(selector: str, reader: _Reader) -> bool:
    """Whether this rule targets something that actually contains text.

    Clipping a card so a photograph follows its rounded corners is ordinary
    CSS and was being refused. Clipping a heading cuts the tail off its own g.
    The difference is not in the rule; it is in what the rule is pointing at,
    which is why this looks at the document rather than at the stylesheet.
    """
    for part in _SELECTOR_PART.findall(selector):
        if part.startswith("."):
            if part[1:] in reader.text_classes:
                return True
        elif part.startswith("#"):
            continue
        elif part.lower() in reader.text_tags:
            return True
    return False


def _fit(style: str, spec: DesignSpec, reader: _Reader) -> list[Finding]:
    """The structural causes of a poster that does not fit its frame.

    None of this proves a layout fits — that needs real font metrics and a real
    browser, and the panel measures it for real before anyone sees the result.
    These are the causes that can be found in the text, and each one of them
    has produced a clipped poster.
    """
    findings = []
    canvas = _CANVAS_RULE.search(style)
    canvas_rule = canvas.group(1) if canvas else ""

    if _NOWRAP.search(style):
        findings.append(
            Finding(
                "Something is set to white-space: nowrap",
                "long text runs past the edge instead of wrapping",
            )
        )
    units = {match[0].lower() for match in _WINDOW_UNITS.findall(style)}
    if units:
        findings.append(
            Finding(
                f"The poster is sized in {', '.join(sorted(units))}",
                "those measure the browser window, and this is looked at in a "
                "panel, a tab, a shared page and on paper - use px, %, em or rem",
            )
        )
    if _FIXED.search(style):
        findings.append(
            Finding("Something uses position: fixed", "it escapes the canvas entirely")
        )
    clipping = [
        selector.strip().replace("\n", " ")
        for selector, body in _RULE.findall(style)
        if _HIDDEN.search(body)
        and ".canvas" not in selector
        and _holds_words(selector, reader)
    ]
    if clipping:
        findings.append(
            Finding(
                f"{clipping[0]} clips its own text",
                "a text block set to overflow: hidden cuts the descenders off "
                "its own headline - give it room instead, or clip a wrapper "
                "that holds no words",
            )
        )
    if _SCROLLS.search(style):
        findings.append(
            Finding("Something scrolls", "a poster is one page, not a scrolling area")
        )
    if canvas and "hidden" not in canvas_rule:
        findings.append(
            Finding(
                "The canvas does not set overflow: hidden",
                "without it a poster that is slightly too tall shares and "
                "prints with a scrollbar and a cut edge",
            )
        )
    if not _BODY_MARGIN.search(style):
        findings.append(
            Finding(
                "The page margin is not zeroed",
                "the browser's default margin pushes the canvas off-centre and "
                "adds a scrollbar in its own tab",
            )
        )
    if spec.width and f"{spec.width}px" not in style:
        findings.append(
            Finding(
                "The canvas is not the size it was given",
                f"expected {spec.width}px by {spec.height}px",
            )
        )
    # Looked for on the canvas rule itself, not anywhere in the stylesheet: a
    # background on `body` does not stop the canvas inheriting the panel's.
    if canvas and "background" not in canvas_rule:
        findings.append(
            Finding(
                "The canvas sets no background",
                "it inherits whatever is behind it and is unreadable half the time",
            )
        )
    return findings


def check(
    document: str, *, spec: DesignSpec, sandbox: SandboxPolicy, max_bytes: int
) -> tuple[Finding, ...]:
    """Everything wrong with this document, in the order worth fixing."""
    reader = _Reader()
    reader.feed(document)
    # Comments out first, so a rule's name in a finding is the selector and not
    # whatever the model wrote above it.
    style = _COMMENT.sub("", reader.style_text)

    findings = [
        *_structure(reader, document),
        *_capability(reader, sandbox),
        *_images(reader, style),
        *_invented(reader),
        *_fit(style, spec, reader),
    ]
    size = len(document.encode())
    if size > max_bytes:
        findings.append(
            Finding("The document is too large", f"{size} bytes, the limit is {max_bytes}")
        )
    return tuple(findings)


def repair_request(document: str, findings: tuple[Finding, ...]) -> str:
    """What to say on the one retry.

    Built from the original request rather than appended to the conversation:
    appending lets a truncation failure and a validation failure stack into one
    incoherent instruction, and the model then fixes neither.
    """
    problems = "\n".join(f"- {finding}" for finding in findings)
    return (
        "The poster you produced has problems that have to be fixed:\n\n"
        f"{problems}\n\n"
        "Fix exactly these. Change nothing else — the design is right, and a "
        "second attempt at it is a different poster rather than a corrected "
        "one. Reply with the complete document. HTML only, starting with "
        "<!DOCTYPE html>.\n\n"
        "THE POSTER AS IT STANDS:\n\n"
        f"{document}"
    )
