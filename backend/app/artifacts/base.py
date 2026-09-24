"""What an artifact is, and what a kind of artifact has to provide.

An artifact is one self-contained HTML document. Not a component, not a
template plus data — a document, because a document is the only format the
browser, the printer, the share link and the download all already understand.
Everything else in this package exists to produce one.

A *kind* — poster today, a deck or a small app later — decides what the
document is allowed to contain, how large the surface is, and how the model is
asked for it. Adding one is a file implementing `ArtifactKind` and a line in
`registry.py`; nothing else in the app learns its name.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ArtifactUnavailable(RuntimeError):
    """The artifact could not be built, with a message safe to show a user."""


@dataclass(frozen=True, slots=True)
class Canvas:
    """The surface a kind composes onto.

    Fixed rather than responsive. A poster has edges, and a model told to fill
    "the page" produces something that fits no page in particular.
    """

    width: int
    height: int
    # What `@page size` should say when the document is printed. A poster is
    # useless as a PDF that reflows.
    page: str = "A4"

    @property
    def ratio(self) -> float:
        return self.width / self.height


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """What a rendered artifact is allowed to do.

    Least privilege, declared per kind rather than once for everything. A
    poster is static art: it has no reason to execute a script, so the frame it
    renders in cannot run one. A kind that genuinely needs scripts asks for
    them and says so here, where the decision is visible.

    The same policy drives the iframe attribute and the response header, so the
    preview and the shared page cannot drift apart.
    """

    scripts: bool = False
    fonts: bool = True
    images: bool = False
    # Whether a form's submit event fires at all. A sandbox without it does
    # not just stop the form sending: it refuses the submission before the
    # event, so no script ever hears about it and a contact form is a button
    # that does nothing. `form-action 'none'` still holds, so nothing is ever
    # sent anywhere; this only lets the document answer its own form.
    forms: bool = False

    @property
    def iframe_sandbox(self) -> str:
        """The `sandbox` attribute value. Empty is the strongest setting there
        is: an opaque origin with scripts, forms and navigation all refused."""
        return " ".join(self._allowed())

    def _allowed(self) -> list[str]:
        allowed = []
        if self.scripts:
            allowed.append("allow-scripts")
        if self.forms:
            allowed.append("allow-forms")
        return allowed

    @property
    def csp(self) -> str:
        """The header for serving the document on its own, in a tab or behind a
        share link. `sandbox` here does what the iframe attribute does for the
        preview — the document gets an opaque origin, so it cannot read a cookie
        or call the API with one."""
        sandbox = " ".join(["sandbox", *self._allowed()])
        # Inline only. An artifact is one self-contained file by contract, so
        # every script it runs is already in it — and `https:` would have been
        # both too much (any origin on the web) and too little (it does not
        # permit an inline script at all, so the document would not run).
        script_src = "'unsafe-inline'" if self.scripts else "'none'"
        style_src = "'unsafe-inline'"
        font_src = "'none'"
        if self.fonts:
            style_src += " https://fonts.googleapis.com"
            font_src = "https://fonts.gstatic.com data:"
        img_src = "data: https:" if self.images else "data:"

        return "; ".join(
            [
                sandbox,
                "default-src 'none'",
                f"script-src {script_src}",
                f"style-src {style_src}",
                f"font-src {font_src}",
                f"img-src {img_src}",
                "connect-src 'none'",
                "form-action 'none'",
                "base-uri 'none'",
            ]
        )


@dataclass(frozen=True, slots=True)
class Brief:
    """What the chat model hands over. Never code — a brief.

    Splitting "understand the request" from "design the thing" is what lets the
    composing step use a different model, a much larger output budget and a
    prompt full of design instruction, none of which has to ride along in the
    chat turn's context on every subsequent message.
    """

    kind: str
    title: str
    brief: str
    style_hints: str = ""
    data: str = ""
    # How many pieces, when the person said. Zero means the kind decides.
    # Asked for as its own field because a number buried in prose is a number
    # the chat model paraphrases away.
    count: int = 0
    # The language the conversation is in, so the poster's own words match it.
    language: str | None = None


@dataclass(frozen=True, slots=True)
class Swatch:
    name: str
    hex: str


@dataclass(frozen=True, slots=True)
class DesignSpec:
    """The direction, chosen before any layout exists.

    Committing to a named aesthetic first — and deliberately in the abstract,
    without naming the subject — is what stops every artifact converging on the
    same look. It is stored rather than inferred, which is what makes a palette
    change a substitution instead of a regeneration.
    """

    movement: str
    rationale: str = ""
    palette: tuple[Swatch, ...] = ()
    display_font: str = ""
    body_font: str = ""
    layout: str = ""
    motif: str = ""
    reference: str = ""
    # The size this artifact chose for itself. Stored rather than taken from
    # the kind, because a printed flyer and something to post are the same kind
    # and different shapes, and the panel has to size the frame to whichever
    # this one is.
    width: int = 0
    height: int = 0
    shape: str = ""
    # What to look for, when the design genuinely wants photographs. Empty
    # means it does not, which is the right answer more often than not.
    image_queries: tuple[str, ...] = ()
    # Where the picture that was found came from, once there is one.
    image_source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "movement": self.movement,
            "rationale": self.rationale,
            "palette": [{"name": s.name, "hex": s.hex} for s in self.palette],
            "display_font": self.display_font,
            "body_font": self.body_font,
            "layout": self.layout,
            "motif": self.motif,
            "reference": self.reference,
            "width": self.width,
            "height": self.height,
            "shape": self.shape,
            "image_queries": list(self.image_queries),
            "image_source": self.image_source,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DesignSpec:
        """Tolerant on the way in. A spec is model output stored in a JSON
        column; a missing key is a worse poster, never a failed page load."""
        palette = tuple(
            Swatch(name=str(s.get("name", "")), hex=str(s.get("hex", "")))
            for s in raw.get("palette") or []
            if isinstance(s, dict)
        )
        return cls(
            movement=str(raw.get("movement", "")),
            rationale=str(raw.get("rationale", "")),
            palette=palette,
            display_font=str(raw.get("display_font", "")),
            body_font=str(raw.get("body_font", "")),
            layout=str(raw.get("layout", "")),
            motif=str(raw.get("motif", "")),
            reference=str(raw.get("reference", "")),
            width=_as_int(raw.get("width")),
            height=_as_int(raw.get("height")),
            shape=str(raw.get("shape", "")),
            image_queries=read_queries(raw),
            image_source=str(raw.get("image_source", "")),
        )


def read_queries(raw: dict[str, Any]) -> tuple[str, ...]:
    """The searches this artifact wants, however the model phrased the field.

    Asked for a list it usually sends one; asked for one it sometimes sends a
    list. Both mean the same thing, and `image_query` is also what earlier
    stored specs used.
    """
    value = raw.get("image_queries", raw.get("image_query"))
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip()[:200] for item in value if str(item).strip())


def _as_int(value: Any) -> int:
    """A dimension the model sent, or zero. Models write "1080px" and "1080"
    with equal confidence."""
    try:
        return int(float(str(value).strip().removesuffix("px")))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class OpenArtifact:
    """The artifact the person is looking at while they type.

    Carried on the turn so "make it warmer" means the poster on screen rather
    than a new one. Without it that sentence has no subject.
    """

    id: Any
    kind: str
    title: str
    html: str
    spec: DesignSpec


@dataclass(frozen=True, slots=True)
class Built:
    """A finished document and what it cost to make."""

    html: str
    spec: DesignSpec
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    build_ms: int = 0
    # What the checks still found. Technical, for the panel.
    findings: tuple[str, ...] = field(default_factory=tuple)
    # One sentence for a person, when something did not go to plan in a way
    # they would otherwise never learn about.
    note: str = ""
    # What was made, in a line the chat model can repeat truthfully -- "four
    # pages: Home, Menu, Story, Visit". It never sees the document, and told
    # nothing, it describes one it imagined.
    summary: str = ""


# --- what a build reports while it runs ---------------------------------


@dataclass(frozen=True, slots=True)
class Step:
    """A phase of the build, for the panel to show. Honest because the pipeline
    genuinely has phases — a single opaque call would have nothing to say."""

    label: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Chunk:
    """Document text as it is written, for the source view."""

    text: str


@dataclass(frozen=True, slots=True)
class Plan:
    """What is about to be made, before any of it exists.

    A deck announces its slides by name first, so the panel can put up the
    whole shape and fill it in. Watching a plan become a deck is a different
    experience from watching a spinner, and it is the same information.
    """

    titles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Designed:
    """The look, the moment it is decided.

    Sent so the thing being built can be shown in its own colours while it is
    still being built, instead of in grey boxes that could belong to anything.
    """

    movement: str
    palette: tuple[str, ...]
    display_font: str
    body_font: str
    # One sentence on what is being made and why it looks like this. For a
    # game it is the loop: what the player will actually be doing.
    rationale: str = ""
    # The shape it has decided on. A poster is a portrait, a deck is
    # widescreen, and a square standing in for both says neither.
    width: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True)
class Part:
    """One finished piece of an artifact that has several.

    A deck is built a slide at a time, and a slide that is done is worth
    looking at while the rest are still coming. `html` is a whole small
    document so the panel can render it without waiting for the others or
    knowing how the finished thing will be assembled.
    """

    index: int
    total: int
    title: str
    html: str


@dataclass(frozen=True, slots=True)
class Finished:
    built: Built


BuildUpdate = Step | Chunk | Plan | Designed | Part | Finished


@runtime_checkable
class ArtifactKind(Protocol):
    """One kind of artifact. Poster today; a deck or an app is another file."""

    name: str
    label: str
    # Written for a model to read when choosing between kinds.
    description: str
    canvas: Canvas
    sandbox: SandboxPolicy

    def build(self, brief: Brief) -> AsyncIterator[BuildUpdate]:
        """Produce the document, reporting as it goes."""
        ...
