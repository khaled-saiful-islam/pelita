"""The poster pipeline: direction, composition, refinement.

Driven by a fake provider, so the whole thing runs without a network call and
every failure path is reachable. The prompts are pinned by hash: they are the
product, and a change to them should show up as a deliberate diff rather than
drifting one word at a time.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator

import pytest

from app.artifacts.base import (
    ArtifactUnavailable,
    Brief,
    Chunk,
    Finished,
    Step,
)
from app.artifacts.model import ArtifactModel, parse_object, strip_fence
from app.artifacts.poster import PosterKind
from app.artifacts.poster_prompts import COMPOSE_SYSTEM, DIRECTION_SYSTEM, REFINE_SYSTEM
from app.providers.base import (
    ChatRequest,
    Completion,
    ProviderError,
    ProviderInfo,
    StreamEvent,
    TokenEvent,
    Usage,
    UsageEvent,
    UsageSource,
)

DIRECTION = {
    "movement": "Midnight Brass",
    "rationale": "brass on near-black carries a late set",
    "palette": [
        {"name": "ground", "hex": "#12151C"},
        {"name": "brass", "hex": "#C8963E"},
        {"name": "bone", "hex": "#EDE6D8"},
    ],
    "display_font": "Gloock",
    "body_font": "Outfit",
    "layout": "the time carries the hierarchy",
    "width": 1080,
    "height": 1350,
    "shape": "made to post, not to print",
    "motif": "a struck bell",
    "reference": "1950s club bills",
}

def poster_html(width: int = 1080, height: int = 1350) -> str:
    """A document that passes every check, at whatever size it was asked for.

    The fake provider behaves like a model that followed its instructions, so
    these tests exercise the pipeline. `test_artifact_validation.py` does the
    opposite and feeds it documents that do not.
    """
    return (
        "<!DOCTYPE html><html><head><style>"
        ":root{--ground:#12151C}"
        "html,body{margin:0;padding:0;background:#000}"
        f".canvas{{width:{width}px;height:{height}px;overflow:hidden;"
        "display:flex;flex-direction:column;background:var(--ground)}"
        "</style></head>"
        '<body><div class="canvas"><h1>Jazz</h1></div></body></html>'
    )


POSTER = poster_html()


class FakeArtifactProvider:
    """Answers the JSON call, then streams the document."""

    def __init__(
        self,
        *,
        direction: object = DIRECTION,
        documents: list[str] | None = None,
        fail_stream: str | None = None,
        fail_decide: str | None = None,
    ) -> None:
        self._direction = direction
        self._documents = documents
        self._size = (1080, 1350)
        self._fail_stream = fail_stream
        self._fail_decide = fail_decide
        self.prompts: list[str] = []
        self.requests: list[ChatRequest] = []
        self.info = ProviderInfo(name="fake", model="fake-artifact", base_url="http://fake")

    async def complete(self, req: ChatRequest) -> Completion:
        self.requests.append(req)
        self.prompts.append(req.messages[0].content)
        if self._fail_decide:
            raise ProviderError(self._fail_decide)
        text = (
            self._direction
            if isinstance(self._direction, str)
            else json.dumps(self._direction)
        )
        return Completion(
            text=text,
            usage=Usage(prompt_tokens=10, completion_tokens=20, source=UsageSource.PROVIDER),
        )

    async def stream_chat(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        self.prompts.append(req.messages[0].content)
        if self._fail_stream:
            raise ProviderError(self._fail_stream)

        asked = re.search(r"exactly (\d+)px by (\d+)px", req.messages[0].content)
        if asked:
            self._size = (int(asked.group(1)), int(asked.group(2)))
        if self._documents is None:
            document = poster_html(*self._size)
        else:
            document = self._documents.pop(0) if self._documents else ""
        for piece in (document[: len(document) // 2], document[len(document) // 2 :]):
            if piece:
                yield TokenEvent(text=piece)
        yield UsageEvent(
            usage=Usage(prompt_tokens=100, completion_tokens=900, source=UsageSource.PROVIDER)
        )


def poster_for(provider, *, refine: bool = True) -> PosterKind:
    return PosterKind(ArtifactModel(provider, max_tokens=4096), refine=refine)


BRIEF = Brief(
    kind="poster",
    title="Friday night jazz",
    brief="A jazz set at Bar Kopi, 9pm, RM35 at the door.",
    style_hints="warm, late",
    data="9pm, RM35",
    language="en",
)


async def build(kind: PosterKind, brief: Brief = BRIEF):
    return [update async for update in kind.build(brief)]


# --- the pipeline -------------------------------------------------------


async def test_a_poster_is_directed_then_composed_then_refined() -> None:
    provider = FakeArtifactProvider()
    updates = await build(poster_for(provider))

    steps = [u.label for u in updates if isinstance(u, Step)]
    assert steps == [
        "Reading the brief",
        "Chose a direction",
        "Composing",
        "Checking it fits",
        "Refining",
    ]
    assert isinstance(updates[-1], Finished)


async def test_the_direction_is_chosen_before_any_layout_exists() -> None:
    """The order is the point: a model asked to design and lay out at once
    reaches for the arrangement it has seen most often."""
    provider = FakeArtifactProvider()
    await build(poster_for(provider))

    assert provider.prompts[0] == DIRECTION_SYSTEM
    assert COMPOSE_SYSTEM in provider.prompts[1]
    assert provider.prompts[2] == REFINE_SYSTEM


async def test_the_chosen_direction_reaches_the_composing_call() -> None:
    provider = FakeArtifactProvider()
    await build(poster_for(provider))

    composing = provider.prompts[1]
    assert "Midnight Brass" in composing
    assert "--ground: #12151C;" in composing
    assert "Gloock" in composing
    assert "1080px by 1350px" in composing


async def test_the_direction_is_reported_so_the_panel_can_show_it() -> None:
    updates = await build(poster_for(FakeArtifactProvider()))
    chose = next(u for u in updates if isinstance(u, Step) and u.label == "Chose a direction")
    assert "Midnight Brass" in chose.detail
    assert "#C8963E" in chose.detail


async def test_the_document_arrives_in_pieces_for_the_source_view() -> None:
    updates = await build(poster_for(FakeArtifactProvider()))
    streamed = "".join(u.text for u in updates if isinstance(u, Chunk))
    assert streamed == POSTER


async def test_the_finished_poster_carries_its_spec_and_its_cost() -> None:
    updates = await build(poster_for(FakeArtifactProvider()))
    built = updates[-1].built

    assert built.html == POSTER
    assert built.spec.movement == "Midnight Brass"
    assert built.spec.palette[0].hex == "#12151C"
    assert built.model == "fake-artifact"
    # Two streamed calls were paid for, not one.
    assert built.completion_tokens == 1800
    assert built.build_ms >= 0


async def test_refinement_can_be_switched_off() -> None:
    provider = FakeArtifactProvider()
    updates = await build(poster_for(provider, refine=False))

    assert [u.label for u in updates if isinstance(u, Step)] == [
        "Reading the brief",
        "Chose a direction",
        "Composing",
        "Checking it fits",
    ]
    assert updates[-1].built.completion_tokens == 900


# --- when things go wrong ----------------------------------------------


async def test_a_refinement_that_came_back_truncated_is_discarded() -> None:
    """A shorter document is not a better one. The composed poster already
    works, and shipping half of it to honour the second call is worse."""
    provider = FakeArtifactProvider(documents=[POSTER, "<!DOCTYPE html><html>"])
    updates = await build(poster_for(provider))

    assert updates[-1].built.html == POSTER


async def test_a_direction_that_is_not_json_still_produces_a_poster() -> None:
    """A plain palette beats a failed request, and retrying the cheap call
    costs more time than it saves."""
    provider = FakeArtifactProvider(direction="I think a warm palette would work nicely.")
    updates = await build(poster_for(provider))

    built = updates[-1].built
    assert built.spec.movement == "Quiet Confidence"
    assert built.spec.palette
    # A4, because nothing said otherwise.
    assert built.html == poster_html(794, 1123)


async def test_the_model_picks_its_own_faces() -> None:
    """Not chosen from a list. A fixed set of families makes every poster this
    app ever makes share a handful of them, which is the same failure as
    everyone reaching for Inter, only slower to notice."""
    provider = FakeArtifactProvider(
        direction={**DIRECTION, "display_font": "Abril Fatface", "body_font": "Karla"}
    )
    updates = await build(poster_for(provider))

    assert updates[-1].built.spec.display_font == "Abril Fatface"
    assert updates[-1].built.spec.body_font == "Karla"


async def test_the_shape_follows_the_brief() -> None:
    """A printed flyer and something to post are the same kind and different
    shapes. The direction decides which this one is."""
    updates = await build(poster_for(FakeArtifactProvider()))
    spec = updates[-1].built.spec
    assert (spec.width, spec.height) == (1080, 1350)


@pytest.mark.parametrize(
    ("sent", "expected"),
    [
        ({"width": 0, "height": 0}, (794, 1123)),
        ({"width": 99999, "height": 5}, (2400, 320)),
        ({"width": "1080px", "height": "1080"}, (1080, 1080)),
    ],
)
async def test_a_canvas_is_clamped_not_trusted(sent: dict, expected: tuple[int, int]) -> None:
    """Clamped rather than chosen: a runaway number produces a canvas the
    browser will not lay out, and a zero produces nothing at all."""
    provider = FakeArtifactProvider(direction={**DIRECTION, **sent})
    updates = await build(poster_for(provider))
    spec = updates[-1].built.spec
    assert (spec.width, spec.height) == expected


async def test_a_provider_failure_is_raised_as_something_sayable() -> None:
    with pytest.raises(ArtifactUnavailable, match="gateway is down"):
        await build(poster_for(FakeArtifactProvider(fail_stream="The gateway is down.")))

    with pytest.raises(ArtifactUnavailable, match="gateway is down"):
        await build(poster_for(FakeArtifactProvider(fail_decide="The gateway is down.")))


async def test_an_empty_document_is_a_failure_not_an_empty_poster() -> None:
    with pytest.raises(ArtifactUnavailable):
        await build(poster_for(FakeArtifactProvider(documents=[""])))


# --- reading what the model sent ---------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Here you go:\n{"a": 1}\nhope that helps', {"a": 1}),
        ("not json at all", {}),
        ("[1, 2, 3]", {}),
    ],
)
def test_json_is_found_however_it_was_wrapped(raw: str, expected: dict) -> None:
    assert parse_object(raw) == expected


def test_a_fence_around_the_document_is_stripped() -> None:
    """The instruction says no fence. Models produce one often enough that
    stripping it is cheaper than a retry."""
    assert strip_fence("```html\n<div>hi</div>\n```") == "<div>hi</div>"
    assert strip_fence("  <div>hi</div>  ") == "<div>hi</div>"


# --- the prompts are the product ---------------------------------------


@pytest.mark.parametrize("prompt", [DIRECTION_SYSTEM, COMPOSE_SYSTEM])
def test_both_design_prompts_carry_the_blocklist(prompt: str) -> None:
    """Naming the tells is most of what separates designed-looking output from
    generated-looking output, and it has to reach both the step that chooses
    colours and the step that lays them out."""
    assert "#F4F1EA" in prompt
    assert "Their words win." in prompt


def test_composition_forbids_everything_the_sandbox_would_block() -> None:
    """The prompt and the sandbox have to agree. A poster told it may use a
    script renders into a frame that refuses to run one, and the failure is
    silent."""
    for banned in ("<script>", "<img>", "background-image url()"):
        assert banned in COMPOSE_SYSTEM
    assert "Never invent a QR code" in COMPOSE_SYSTEM


def test_composition_requires_the_palette_as_variables() -> None:
    """This is what makes a later palette change a substitution rather than a
    regeneration."""
    assert "custom properties on :root" in COMPOSE_SYSTEM
    assert "Never repeat a" in COMPOSE_SYSTEM
    assert "lets the palette be changed later without" in COMPOSE_SYSTEM


def test_refinement_is_forbidden_from_adding() -> None:
    assert "REFINE. DO NOT ADD." in REFINE_SYSTEM
    assert "take one thing off" in REFINE_SYSTEM


def test_the_prompts_have_not_drifted() -> None:
    """One hash over all three, so a change to the product is a change to this
    line. If you meant it, update the digest in the same commit as the prompt."""
    combined = "\n".join([DIRECTION_SYSTEM, COMPOSE_SYSTEM, REFINE_SYSTEM]).encode()
    assert hashlib.sha256(combined).hexdigest()[:16] == "7a1dc01932f32d19"
