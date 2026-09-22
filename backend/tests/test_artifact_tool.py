"""Making an artifact from a chat turn.

The whole path: the model asks, a kind builds, the turn stores it and the
browser is told where it is — driven by fakes, so none of it needs a network or
a real model.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.artifacts.base import (
    ArtifactUnavailable,
    Brief,
    BuildUpdate,
    Built,
    Canvas,
    Chunk,
    DesignSpec,
    Finished,
    SandboxPolicy,
    Step,
)
from app.core.config import Settings
from app.db.models.artifact import Artifact
from app.providers.base import Role, ToolCall
from app.services.events import (
    ArtifactDeltaEvent,
    ArtifactDoneEvent,
    ArtifactStartEvent,
    ArtifactStepEvent,
    ToolEvent,
)
from app.tools.artifact import CreateArtifactTool
from app.tools.base import ToolUnavailable
from app.tools.registry import build_tools
from tests.test_chat_service import FakeProvider, build_service, collect

DOCUMENT = "<!DOCTYPE html><html><body><div class='canvas'>ok</div></body></html>"


class FakePoster:
    name = "poster"
    label = "Poster"
    description = "A poster."
    canvas = Canvas(width=794, height=1123)
    sandbox = SandboxPolicy(scripts=False)

    def __init__(self, *, fail: str | None = None) -> None:
        self._fail = fail
        self.briefs: list[Brief] = []

    async def build(self, brief: Brief) -> AsyncIterator[BuildUpdate]:
        self.briefs.append(brief)
        if self._fail:
            raise ArtifactUnavailable(self._fail)
        yield Step(label="Chose a direction", detail="Midnight Brass")
        yield Chunk(text=DOCUMENT)
        yield Finished(
            built=Built(
                html=DOCUMENT,
                spec=DesignSpec(movement="Midnight Brass", width=794, height=1123),
                model="fake-artifact",
                completion_tokens=900,
                findings=("The canvas sets no background",),
            )
        )


def tool_for(kind: Any) -> CreateArtifactTool:
    return CreateArtifactTool({kind.name: kind})


ARGUMENTS = {
    "kind": "poster",
    "title": "Friday night jazz",
    "brief": "a late set at Bar Kopi",
    "data": "9pm, RM35",
}


def asking_for_a_poster(session, registry, kind, *, arguments: dict | None = None):
    tool = tool_for(kind)
    provider = FakeProvider(
        ["Made you one."],
        tool_calls=[
            ToolCall(
                id="call_1",
                name=tool.name,
                arguments=json.dumps(ARGUMENTS if arguments is None else arguments),
            )
        ],
    )
    service = build_service(
        session, provider, registry, tools={tool.name: tool}, tool_calling=True
    )
    return provider, service


async def turn(service, db_user):
    return await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="make me a poster for friday",
        search_mode="always",
    )


# --- what the model is offered -----------------------------------------


def test_the_kinds_are_the_enum_the_model_chooses_from() -> None:
    """A new kind is offered by existing. There is no second list to update."""
    tool = tool_for(FakePoster())
    assert tool.parameters["properties"]["kind"]["enum"] == ["poster"]
    assert tool.parameters["required"] == ["kind", "title", "brief"]


def test_the_tool_refuses_to_take_code() -> None:
    """The split is the design: the model writes a brief, a different model
    with a much larger budget does the making."""
    described = json.dumps(tool_for(FakePoster()).parameters)
    assert "Never write HTML or CSS here" in described
    assert "code" not in tool_for(FakePoster()).parameters["properties"]


def test_no_artifact_model_means_no_tool_at_all() -> None:
    off = Settings(_env_file=None, serpapi_key="", artifact_model="")  # type: ignore[call-arg]
    assert build_tools(off) == {}

    on = Settings(_env_file=None, serpapi_key="", artifact_model="m")  # type: ignore[call-arg]
    # Both registered; the turn decides whether editing is offered, since
    # there is nothing to edit until something is open.
    assert set(build_tools(on)) == {"create_artifact", "edit_artifact"}


async def test_an_unknown_kind_is_refused_by_name() -> None:
    with pytest.raises(ToolUnavailable, match="poster"):
        async for _ in tool_for(FakePoster()).stream(kind="mural", title="x", brief="y"):
            pass


# --- the turn -----------------------------------------------------------


async def test_the_brief_reaches_the_kind_whole(session, db_user, registry) -> None:
    kind = FakePoster()
    _, service = asking_for_a_poster(session, registry, kind)

    await turn(service, db_user)

    assert len(kind.briefs) == 1
    brief = kind.briefs[0]
    assert brief.title == "Friday night jazz"
    assert brief.brief == "a late set at Bar Kopi"
    assert brief.data == "9pm, RM35"


async def test_the_panel_is_told_it_is_starting_before_any_work(
    session, db_user, registry
) -> None:
    """So it can open and say what is coming, rather than appearing fully
    formed a minute later."""
    _, service = asking_for_a_poster(session, registry, FakePoster())
    events = await turn(service, db_user)

    start = next(e for e in events if isinstance(e, ArtifactStartEvent))
    step = next(e for e in events if isinstance(e, ArtifactStepEvent))
    assert start.kind == "poster"
    assert start.title == "Friday night jazz"
    assert events.index(start) < events.index(step)


async def test_the_document_streams_for_the_source_view(session, db_user, registry) -> None:
    _, service = asking_for_a_poster(session, registry, FakePoster())
    events = await turn(service, db_user)

    assert "".join(e.text for e in events if isinstance(e, ArtifactDeltaEvent)) == DOCUMENT


async def test_the_finished_artifact_is_stored_and_located(
    session, db_user, registry
) -> None:
    _, service = asking_for_a_poster(session, registry, FakePoster())
    events = await turn(service, db_user)

    done = next(e for e in events if isinstance(e, ArtifactDoneEvent))
    assert done.kind == "poster"
    assert done.version == 1
    assert (done.width, done.height) == (794, 1123)
    assert done.findings == ("The canvas sets no background",)

    stored = await session.get(Artifact, done.artifact_id)
    assert stored is not None
    assert stored.user_id == db_user.id
    assert stored.versions[0].html == DOCUMENT
    assert stored.versions[0].design_spec["movement"] == "Midnight Brass"


async def test_the_finished_frame_names_the_artifact_the_same_way_rest_does(
    session, db_user, registry
) -> None:
    """Two names for one id is how a card ends up pointing at `undefined` and
    the panel silently refuses to open. Found in a browser, not here."""
    from app.api.routes.chat import _to_sse

    _, service = asking_for_a_poster(session, registry, FakePoster())
    events = await turn(service, db_user)
    done = next(e for e in events if isinstance(e, ArtifactDoneEvent))

    frame = _to_sse(done)
    assert frame is not None
    payload = json.loads(frame["data"])
    assert payload["id"] == str(done.artifact_id)
    assert "artifact_id" not in payload


async def test_the_artifact_belongs_to_the_answer_that_made_it(
    session, db_user, registry
) -> None:
    """So the transcript can put a card in the right place after a reload."""
    _, service = asking_for_a_poster(session, registry, FakePoster())
    events = await turn(service, db_user)

    done = next(e for e in events if isinstance(e, ArtifactDoneEvent))
    stored = await session.get(Artifact, done.artifact_id)
    assert stored is not None
    assert stored.message_id is not None


async def test_the_model_is_told_it_exists_but_never_shown_it(
    session, db_user, registry
) -> None:
    """Replaying thousands of tokens of CSS into the next request buys nothing
    and costs everything. The person can already see it."""
    provider, service = asking_for_a_poster(session, registry, FakePoster())
    await turn(service, db_user)

    answered = [
        m for r in provider.requests for m in r.messages if m.role is Role.TOOL
    ]
    assert answered
    assert "on screen" in answered[0].content
    # Not the document. Replaying thousands of tokens of CSS buys nothing.
    for markup in ("<div", "<!DOCTYPE", "class=", "<style"):
        assert markup not in answered[0].content


async def test_a_build_that_fails_degrades_the_turn_rather_than_ending_it(
    session, db_user, registry
) -> None:
    _, service = asking_for_a_poster(
        session, registry, FakePoster(fail="The design model is unavailable.")
    )
    events = await turn(service, db_user)

    assert any(isinstance(e, ToolEvent) and e.status == "failed" for e in events)
    assert not any(isinstance(e, ArtifactDoneEvent) for e in events)
    # The turn still answered.
    assert any(isinstance(e, ArtifactStartEvent) for e in events)


async def test_a_search_tool_does_not_produce_artifact_steps(
    session, db_user, registry
) -> None:
    """Only a build has steps worth naming on the panel."""
    from tests.test_tool_protocol import SurveyTool, asking_for

    _, service = asking_for(SurveyTool(), {"topic": "kopi"}, session, registry)
    events = await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="survey something",
        search_mode="always",
    )

    assert not any(isinstance(e, ArtifactStepEvent) for e in events)
    assert any(isinstance(e, ToolEvent) for e in events)


# --- changing what is open ----------------------------------------------


class RevisableFakePoster(FakePoster):
    def __init__(self) -> None:
        super().__init__()
        self.instructions: list[str] = []

    async def revise(self, *, html: str, spec: DesignSpec, instruction: str):
        self.instructions.append(instruction)
        yield Step(label="Redrawing", detail="")
        yield Finished(
            built=Built(
                html=f"{DOCUMENT}<!-- {instruction} -->",
                spec=spec,
                model="fake-artifact",
                completion_tokens=400,
            )
        )


def asking_to_change(session, registry, kind, instruction="make it warmer"):
    from app.tools.artifact import EditArtifactTool

    tool = EditArtifactTool({kind.name: kind})
    provider = FakeProvider(
        ["Warmer it is."],
        tool_calls=[
            ToolCall(
                id="call_1",
                name=tool.name,
                arguments=json.dumps({"instruction": instruction}),
            )
        ],
    )
    service = build_service(
        session, provider, registry, tools={tool.name: tool}, tool_calling=True
    )
    return provider, service


async def existing_poster(session, db_user, registry):
    """A poster already made, the way a real one gets there."""
    _, service = asking_for_a_poster(session, registry, FakePoster())
    events = await turn(service, db_user)
    done = next(e for e in events if isinstance(e, ArtifactDoneEvent))
    return done


async def test_a_change_from_the_chat_box_becomes_the_next_version(
    session, db_user, registry
) -> None:
    """Typed into the same box as everything else. "Make it warmer" means the
    poster on screen, not a new poster about warmth."""
    made = await existing_poster(session, db_user, registry)
    kind = RevisableFakePoster()
    _, service = asking_to_change(session, registry, kind)

    events = await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="make it warmer",
        search_mode="always",
        artifact_id=made.artifact_id,
    )

    assert kind.instructions == ["make it warmer"]
    done = next(e for e in events if isinstance(e, ArtifactDoneEvent))
    assert done.artifact_id == made.artifact_id
    assert done.version == 2

    stored = await session.get(Artifact, made.artifact_id)
    assert stored is not None
    assert len(stored.versions) == 2
    assert "make it warmer" in stored.versions[1].html


async def test_the_tool_is_not_offered_when_nothing_is_open(
    session, db_user, registry
) -> None:
    """Offering a way to change nothing invites the model to try."""
    kind = RevisableFakePoster()
    provider, service = asking_to_change(session, registry, kind)

    await collect(
        session and service,
        user_id=db_user.id,
        conversation_id=None,
        content="make it warmer",
        search_mode="always",
    )

    offered = [t["function"]["name"] for t in (provider.requests[0].tools or ())]
    assert offered == []
    assert kind.instructions == []


async def test_an_open_artifact_offers_it(session, db_user, registry) -> None:
    made = await existing_poster(session, db_user, registry)
    kind = RevisableFakePoster()
    provider, service = asking_to_change(session, registry, kind)

    await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="make it warmer",
        search_mode="always",
        artifact_id=made.artifact_id,
    )

    offered = [t["function"]["name"] for t in (provider.requests[0].tools or ())]
    assert offered == ["edit_artifact"]


async def test_somebody_elses_artifact_is_not_open_to_you(
    session, db_user, registry
) -> None:
    """Ownership is a parameter of the lookup, here as everywhere."""
    from uuid import uuid4

    kind = RevisableFakePoster()
    provider, service = asking_to_change(session, registry, kind)

    await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="make it warmer",
        search_mode="always",
        artifact_id=uuid4(),
    )

    assert [t["function"]["name"] for t in (provider.requests[0].tools or ())] == []


async def test_turning_search_off_does_not_turn_off_making_things(
    session, db_user, registry
) -> None:
    """Reported as "it is not working": asked for a slide deck, the model typed
    the headings into the chat instead. Search was off, and the turn returned
    before offering any tool at all — so there was nothing to call.
    """
    kind = FakePoster()
    provider, service = asking_for_a_poster(session, registry, kind)

    await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="make me a poster",
        search_mode="off",
    )

    offered = [t["function"]["name"] for t in (provider.requests[0].tools or ())]
    assert offered == ["create_artifact"]
    assert len(kind.briefs) == 1


async def test_searching_is_what_the_search_control_governs(
    session, db_user, registry
) -> None:
    from app.tools.artifact import CreateArtifactTool
    from app.tools.web_search import WebSearchTool
    from tests.test_tool_protocol import WeatherTool

    assert getattr(WebSearchTool, "searches", False) is True
    # Everything else is left alone by it.
    assert getattr(WeatherTool, "searches", False) is False
    assert getattr(CreateArtifactTool, "searches", False) is False


async def test_search_on_every_message_never_forces_a_poster(
    session, db_user, registry
) -> None:
    """With only a make-something tool on the table, forcing a call would have
    it make something nobody asked for."""
    _, service = asking_for_a_poster(session, registry, FakePoster())

    events = await collect(
        service,
        user_id=db_user.id,
        conversation_id=None,
        content="hello",
        search_mode="always",
    )

    assert events  # the turn ran rather than being forced into a tool
