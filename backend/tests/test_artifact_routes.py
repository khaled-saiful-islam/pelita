"""Reading an artifact back after the stream is over."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.core.security import hash_password
from app.db.models.conversation import Conversation
from app.db.models.user import User
from app.db.repositories.artifacts import SqlArtifactRepository

DOCUMENT = "<!DOCTYPE html><html><body><div class='canvas'>poster</div></body></html>"


@pytest.fixture
def api(session):
    from app.api.deps import get_session
    from app.main import create_app

    app = create_app()

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def conversation(session, db_user) -> Conversation:
    record = Conversation(user_id=db_user.id, title="Posters")
    session.add(record)
    await session.flush()
    return record


@pytest.fixture
async def stranger(session) -> User:
    user = User(
        username="intruder",
        email="intruder@example.com",
        password_hash=hash_password("hunter2hunter2"),
        display_name="Intruder",
    )
    session.add(user)
    await session.flush()
    return user


async def sign_in(client, username="tester") -> None:
    response = await client.post(
        "/api/auth/signin", json={"identifier": username, "password": "hunter2hunter2"}
    )
    assert response.status_code == 200, response.text


@pytest.fixture
async def artifact(session, db_user, conversation):
    return await SqlArtifactRepository(session).create(
        conversation_id=conversation.id,
        user_id=db_user.id,
        message_id=None,
        kind="poster",
        title="Friday night jazz",
        html=DOCUMENT,
        design_spec={"movement": "Midnight Brass", "width": 794, "height": 1123},
    )


async def test_an_artifact_comes_back_with_its_document(api, artifact) -> None:
    async with api as client:
        await sign_in(client)
        response = await client.get(f"/api/artifacts/{artifact.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Friday night jazz"
    assert body["html"] == DOCUMENT
    assert (body["width"], body["height"]) == (794, 1123)
    assert body["version"] == 1


async def test_a_static_kind_reports_a_frame_that_cannot_run_a_script(
    api, artifact
) -> None:
    """The component does not decide this. The kind does, so the preview and a
    shared page cannot end up disagreeing."""
    async with api as client:
        await sign_in(client)
        body = (await client.get(f"/api/artifacts/{artifact.id}")).json()
    assert body["sandbox"] == ""


async def test_the_raw_document_is_served_under_its_own_sandbox(api, artifact) -> None:
    """`sandbox` in a header does for a whole document what the attribute does
    for a frame: an opaque origin, so it cannot read a cookie or call the API
    with one even though it is on the same host."""
    async with api as client:
        await sign_in(client)
        response = await client.get(f"/api/artifacts/{artifact.id}/raw")

    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    assert policy.startswith("sandbox;")
    assert "script-src 'none'" in policy
    assert response.headers["cache-control"] == "private, no-store"
    assert response.text == DOCUMENT


async def test_somebody_elses_artifact_does_not_exist(api, artifact, stranger) -> None:
    async with api as client:
        await sign_in(client, "intruder")
        assert (await client.get(f"/api/artifacts/{artifact.id}")).status_code == 404
        assert (await client.get(f"/api/artifacts/{artifact.id}/raw")).status_code == 404


async def test_an_artifact_that_never_existed_reads_the_same_way(api, db_user) -> None:
    async with api as client:
        await sign_in(client)
        assert (await client.get(f"/api/artifacts/{uuid4()}")).status_code == 404


async def test_a_conversation_lists_what_it_made(api, artifact, conversation) -> None:
    """So a reload can put the cards back in the transcript."""
    async with api as client:
        await sign_in(client)
        response = await client.get(f"/api/conversations/{conversation.id}/artifacts")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["title"] for item in items] == ["Friday night jazz"]
    assert "html" not in items[0]


async def test_an_earlier_version_can_be_read_back(api, artifact, session) -> None:
    await SqlArtifactRepository(session).add_version(
        artifact, html="<!DOCTYPE html><html><body>v2</body></html>", design_spec={}
    )

    async with api as client:
        await sign_in(client)
        current = (await client.get(f"/api/artifacts/{artifact.id}")).json()
        first = (await client.get(f"/api/artifacts/{artifact.id}?version=1")).json()

    assert current["version"] == 2
    assert first["html"] == DOCUMENT
    assert [v["version"] for v in current["versions"]] == [1, 2]
