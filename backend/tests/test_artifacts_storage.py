"""The artifact seam: a kind nothing knows about, and versions that accumulate.

These tests exist to keep the same promise the tool seam makes — adding a kind
is a file and a registry line, and storage never learns its name.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from app.artifacts.base import (
    ArtifactKind,
    Brief,
    BuildUpdate,
    Built,
    Canvas,
    DesignSpec,
    Finished,
    SandboxPolicy,
    Step,
    Swatch,
)
from app.artifacts.registry import build_kinds
from app.core.config import Settings
from app.core.security import hash_password
from app.db.models.conversation import Conversation
from app.db.models.user import User
from app.db.repositories.artifacts import SqlArtifactRepository


@pytest.fixture
async def db_conversation(session, db_user) -> Conversation:
    conversation = Conversation(user_id=db_user.id, title="Posters")
    session.add(conversation)
    await session.flush()
    return conversation


@pytest.fixture
async def other_user(session) -> User:
    user = User(
        username="someone-else",
        email="else@example.com",
        password_hash=hash_password("hunter2hunter2"),
        display_name="Else",
    )
    session.add(user)
    await session.flush()
    return user


class RecipeCard(ArtifactKind):
    """A kind the codebase has never heard of, added from outside."""

    name = "recipe"
    label = "Recipe card"
    description = "A card with a recipe on it."
    canvas = Canvas(width=600, height=800, page="A5")
    sandbox = SandboxPolicy(scripts=False)

    async def build(self, brief: Brief) -> AsyncIterator[BuildUpdate]:
        yield Step(label="Choosing a direction", detail="Warm Kitchen")
        yield Finished(
            built=Built(
                html="<div class='canvas'>nasi lemak</div>",
                spec=DesignSpec(
                    movement="Warm Kitchen",
                    palette=(Swatch(name="ink", hex="#101010"),),
                ),
                model="fake-artifact",
                completion_tokens=12,
            )
        )


# --- the protocol -------------------------------------------------------


def test_a_kind_the_codebase_has_never_heard_of_satisfies_the_protocol() -> None:
    assert isinstance(RecipeCard(), ArtifactKind)


def test_no_model_means_the_capability_does_not_exist() -> None:
    """The UI reads this through /api/config and offers nothing, rather than a
    button that always fails."""
    assert build_kinds(Settings(_env_file=None, artifact_model="")) == {}  # type: ignore[call-arg]
    assert (
        build_kinds(
            Settings(_env_file=None, artifact_model="m", artifacts_enabled=False)  # type: ignore[call-arg]
        )
        == {}
    )


def test_a_static_kind_renders_in_a_frame_that_cannot_run_a_script() -> None:
    """Least privilege, declared by the kind. A poster is art; it has no reason
    to execute anything, so the frame refuses to."""
    static = SandboxPolicy(scripts=False)
    assert static.iframe_sandbox == ""
    assert "script-src 'none'" in static.csp
    assert static.csp.startswith("sandbox;")

    interactive = SandboxPolicy(scripts=True)
    assert interactive.iframe_sandbox == "allow-scripts"
    assert interactive.csp.startswith("sandbox allow-scripts;")


def test_a_design_spec_survives_the_round_trip_through_json() -> None:
    spec = DesignSpec(
        movement="Midnight Brass",
        rationale="brass on near-black",
        palette=(Swatch(name="ink", hex="#12151C"), Swatch(name="brass", hex="#C8963E")),
        display_font="Gloock",
        body_font="Outfit",
    )
    assert DesignSpec.from_dict(spec.as_dict()) == spec


def test_a_half_written_spec_still_loads() -> None:
    """Model output in a JSON column. A missing key is a worse poster, never a
    page that will not open."""
    spec = DesignSpec.from_dict({"movement": "Something", "palette": ["not a dict"]})
    assert spec.movement == "Something"
    assert spec.palette == ()


# --- storage ------------------------------------------------------------


async def build_one(session, user, conversation, **kwargs):
    repo = SqlArtifactRepository(session)
    return repo, await repo.create(
        conversation_id=conversation.id,
        user_id=user.id,
        message_id=None,
        kind="recipe",
        title="Nasi lemak",
        html="<div>one</div>",
        design_spec={"movement": "Warm Kitchen"},
        **kwargs,
    )


async def test_creating_an_artifact_writes_its_first_version(
    session, db_user, db_conversation
) -> None:
    repo, artifact = await build_one(session, db_user, db_conversation)

    assert artifact.current_version == 1
    version = await repo.version(artifact)
    assert version is not None
    assert version.version == 1
    assert version.html == "<div>one</div>"
    assert version.size_bytes == len("<div>one</div>")


async def test_an_edit_adds_a_version_and_leaves_the_old_one_readable(
    session, db_user, db_conversation
) -> None:
    """An edit that erases what it replaced cannot be undone, and the version
    selector would have nothing to select."""
    repo, artifact = await build_one(session, db_user, db_conversation)

    await repo.add_version(artifact, html="<div>two</div>", design_spec={"movement": "Warm"})

    assert artifact.current_version == 2
    current = await repo.version(artifact)
    first = await repo.version(artifact, 1)
    assert current is not None and current.html == "<div>two</div>"
    assert first is not None and first.html == "<div>one</div>"


async def test_versions_are_numbered_per_artifact_not_per_conversation(
    session, db_user, db_conversation
) -> None:
    """Two artifacts in one chat must not share a counter — a poster and a deck
    would leapfrog each other for no reason anyone could explain later."""
    repo, first = await build_one(session, db_user, db_conversation)
    await repo.add_version(first, html="<div>1v2</div>", design_spec={})

    _, second = await build_one(session, db_user, db_conversation)

    assert first.current_version == 2
    assert second.current_version == 1


async def test_ownership_is_a_parameter_of_the_lookup(
    session, db_user, db_conversation, other_user
) -> None:
    """Someone else's artifact is indistinguishable from one that never was."""
    _, artifact = await build_one(session, db_user, db_conversation)
    repo = SqlArtifactRepository(session)

    assert await repo.get(artifact.id, db_user.id) is not None
    assert await repo.get(artifact.id, other_user.id) is None
    assert await repo.get(uuid4(), db_user.id) is None


async def test_the_per_conversation_count_is_counted_not_tracked(
    session, db_user, db_conversation
) -> None:
    """Counted, so deleting one frees its slot."""
    repo = SqlArtifactRepository(session)
    assert await repo.count_for_conversation(db_conversation.id) == 0

    _, artifact = await build_one(session, db_user, db_conversation)
    assert await repo.count_for_conversation(db_conversation.id) == 1

    await session.delete(artifact)
    await session.flush()
    assert await repo.count_for_conversation(db_conversation.id) == 0


@pytest.mark.parametrize("attribute", ["conversation", "user"])
async def test_deleting_the_owner_takes_the_artifact_with_it(
    session, db_user, db_conversation, attribute
) -> None:
    """A live artifact belonging to a deleted account is the worst failure this
    could have."""
    repo, artifact = await build_one(session, db_user, db_conversation)
    artifact_id = artifact.id

    await session.delete(db_conversation if attribute == "conversation" else db_user)
    await session.flush()
    session.expunge_all()

    assert await repo.get(artifact_id, db_user.id) is None
