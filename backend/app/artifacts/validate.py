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
_NOWRAP_HEADING = re.compile(
    r"(h1|h2|h3|\.headline|\.title)[^{}]*\{[^{}]*white-space\s*:\s*nowrap", re.IGNORECASE | re.S
)
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
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        if tag == "script":
            self.scripts += 1
        if tag == "style":
            self._in_style = True
        if tag == "img":
            self.images += 1
        for name, value in attrs:
            if name.startswith("on"):
                self.event_attributes.append(name)
            if name == "class" and value and "canvas" in value.split():
                self.has_canvas = True
            if name in {"src", "href"} and value:
                self._note_url(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.style_text += data

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
                "The document contains an <img>",
                "there is no picture to point it at, so it renders as a broken box",
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


def _fit(style: str, spec: DesignSpec) -> list[Finding]:
    findings = []
    if _NOWRAP_HEADING.search(style):
        findings.append(
            Finding(
                "A heading is set to white-space: nowrap",
                "a long title runs off the page instead of wrapping",
            )
        )
    if spec.width and f"{spec.width}px" not in style:
        findings.append(
            Finding(
                "The canvas is not the size it was given",
                f"expected {spec.width}px by {spec.height}px",
            )
        )
    if "background" not in style:
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
    style = reader.style_text

    findings = [
        *_structure(reader, document),
        *_capability(reader, sandbox),
        *_images(reader, style),
        *_invented(reader),
        *_fit(style, spec),
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
