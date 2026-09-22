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
    from app.api.deps import get_session, limit_auth
    from app.main import create_app

    app = create_app()

    async def _session():
        yield session

    async def _no_auth_limit() -> None:
        return None

    app.dependency_overrides[get_session] = _session
    # These tests sign in on nearly every case, and the sign-in limit is
    # counted per address across the whole run. Without this they spend the
    # budget that `test_rate_limit.py` exists to measure, and that file fails
    # in a full run while passing on its own.
    app.dependency_overrides[limit_auth] = _no_auth_limit
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


# --- sharing ------------------------------------------------------------


async def test_a_shared_artifact_needs_no_account(api, artifact) -> None:
    async with api as client:
        await sign_in(client)
        share = (await client.post(f"/api/artifacts/{artifact.id}/share")).json()
        client.cookies.clear()
        # No cookie at all.
        response = await client.get(f"/api/shares/artifacts/{share['token']}")

    assert response.status_code == 200
    assert response.text == DOCUMENT


async def test_the_token_is_the_credential(api, artifact) -> None:
    """256 bits. The URL is the only thing protecting this, so guessing must
    not be a strategy."""
    from app.services.artifact_share_service import TOKEN_BYTES

    async with api as client:
        await sign_in(client)
        share = (await client.post(f"/api/artifacts/{artifact.id}/share")).json()

    assert TOKEN_BYTES == 32
    assert len(share["token"]) >= 40
    assert share["url"].endswith(f"/a/{share['token']}")


async def test_a_shared_poster_cannot_use_the_host_it_is_served_from(api, artifact) -> None:
    """The only unauthenticated route returning a document. In an opaque origin
    it can neither read a cookie nor call the API with one."""
    async with api as client:
        await sign_in(client)
        share = (await client.post(f"/api/artifacts/{artifact.id}/share")).json()
        client.cookies.clear()
        response = await client.get(f"/api/shares/artifacts/{share['token']}")

    assert response.headers["content-security-policy"].startswith("sandbox;")
    assert "noindex" in response.headers["x-robots-tag"]
    assert response.headers["cache-control"] == "no-store"


async def test_sharing_again_keeps_the_link_working(api, artifact, session) -> None:
    """A link already sent stays alive; killing it is a different intent with
    its own button."""
    async with api as client:
        await sign_in(client)
        first = (await client.post(f"/api/artifacts/{artifact.id}/share")).json()
        await SqlArtifactRepository(session).add_version(
            artifact, html="<!DOCTYPE html><html><body>v2</body></html>", design_spec={}
        )
        second = (await client.post(f"/api/artifacts/{artifact.id}/share")).json()
        client.cookies.clear()
        served = await client.get(f"/api/shares/artifacts/{first['token']}")

    assert second["token"] == first["token"]
    assert second["version"] == 2
    assert "v2" in served.text


async def test_a_share_is_a_copy_so_a_later_edit_is_not_published(
    api, artifact, session
) -> None:
    """A link that followed the artifact would republish every later edit
    without the owner deciding to."""
    async with api as client:
        await sign_in(client)
        share = (await client.post(f"/api/artifacts/{artifact.id}/share")).json()
        await SqlArtifactRepository(session).add_version(
            artifact, html="<html><body>SECRET</body></html>", design_spec={}
        )
        client.cookies.clear()
        response = await client.get(f"/api/shares/artifacts/{share['token']}")

    assert "SECRET" not in response.text
    assert response.text == DOCUMENT


async def test_a_revoked_link_answers_like_one_that_never_existed(api, artifact) -> None:
    """So a token cannot be used to learn which ones are real."""
    async with api as client:
        await sign_in(client)
        share = (await client.post(f"/api/artifacts/{artifact.id}/share")).json()
        await client.delete(f"/api/artifacts/{artifact.id}/share")
        client.cookies.clear()
        revoked = await client.get(f"/api/shares/artifacts/{share['token']}")
        never = await client.get("/api/shares/artifacts/nonsense-token")

    assert revoked.status_code == never.status_code == 404
    assert revoked.json() == never.json()


async def test_revoking_twice_is_not_an_error(api, artifact) -> None:
    async with api as client:
        await sign_in(client)
        await client.post(f"/api/artifacts/{artifact.id}/share")
        assert (await client.delete(f"/api/artifacts/{artifact.id}/share")).status_code == 204
        assert (await client.delete(f"/api/artifacts/{artifact.id}/share")).status_code == 204


async def test_somebody_else_cannot_share_your_artifact(api, artifact, stranger) -> None:
    async with api as client:
        await sign_in(client, "intruder")
        assert (await client.post(f"/api/artifacts/{artifact.id}/share")).status_code == 404


# --- downloading --------------------------------------------------------


async def test_downloading_the_document_gives_a_named_file(api, artifact) -> None:
    async with api as client:
        await sign_in(client)
        response = await client.get(f"/api/artifacts/{artifact.id}/download?format=html")

    assert response.status_code == 200
    assert response.text == DOCUMENT
    assert response.headers["content-disposition"] == (
        'attachment; filename="Friday-night-jazz.html"'
    )


async def test_a_title_that_would_break_a_filesystem_is_cleaned(
    api, session, db_user, conversation
) -> None:
    made = await SqlArtifactRepository(session).create(
        conversation_id=conversation.id,
        user_id=db_user.id,
        message_id=None,
        kind="poster",
        title="Raya / 2026: open house!",
        html=DOCUMENT,
        design_spec={},
    )
    async with api as client:
        await sign_in(client)
        response = await client.get(f"/api/artifacts/{made.id}/download?format=html")

    disposition = response.headers["content-disposition"]
    assert "/" not in disposition.split("filename=")[1]
    assert disposition.endswith('.html"')


# --- editing the words --------------------------------------------------


TEXT_POSTER = (
    "<!DOCTYPE html><html><head><style>.canvas{width:794px}</style></head>"
    '<body><div class="canvas"><h1>Friday night jazz</h1><p>RM35</p></div></body></html>'
)


@pytest.fixture
async def wordy(session, db_user, conversation):
    return await SqlArtifactRepository(session).create(
        conversation_id=conversation.id,
        user_id=db_user.id,
        message_id=None,
        kind="poster",
        title="Jazz",
        html=TEXT_POSTER,
        design_spec={"movement": "Midnight Brass", "width": 794, "height": 1123},
    )


async def test_the_words_can_be_read_back_in_order(api, wordy) -> None:
    async with api as client:
        await sign_in(client)
        words = (await client.get(f"/api/artifacts/{wordy.id}/text")).json()

    assert words == ["Friday night jazz", "RM35"]


async def test_changing_a_word_costs_no_model_call(api, wordy) -> None:
    async with api as client:
        await sign_in(client)
        response = await client.post(
            f"/api/artifacts/{wordy.id}/text",
            json={"changes": [{"index": 1, "text": "RM40"}]},
        )

    assert response.status_code == 200
    body = response.json()
    assert "RM40" in body["html"]
    assert "Friday night jazz" in body["html"]
    # The stylesheet is untouched, byte for byte.
    assert ".canvas{width:794px}" in body["html"]


async def test_fixing_a_word_does_not_make_a_new_version(api, wordy) -> None:
    """Fixing a typo is not a new draft. A version list where every entry
    differs by one character is a version list nobody reads."""
    async with api as client:
        await sign_in(client)
        body = (
            await client.post(
                f"/api/artifacts/{wordy.id}/text",
                json={"changes": [{"index": 1, "text": "RM40"}]},
            )
        ).json()

    assert body["version"] == 1
    assert len(body["versions"]) == 1
    assert "RM40" in body["html"]
    assert "RM35" not in body["html"]


async def test_an_edit_that_changes_nothing_does_not_make_a_version(api, wordy) -> None:
    async with api as client:
        await sign_in(client)
        body = (
            await client.post(f"/api/artifacts/{wordy.id}/text", json={"changes": []})
        ).json()

    assert body["version"] == 1


async def test_words_cannot_carry_markup_in(api, wordy) -> None:
    async with api as client:
        await sign_in(client)
        body = (
            await client.post(
                f"/api/artifacts/{wordy.id}/text",
                json={"changes": [{"index": 0, "text": "<script>alert(1)</script>"}]},
            )
        ).json()

    assert "<script>" not in body["html"]
    assert "&lt;script&gt;" in body["html"]


async def test_somebody_else_cannot_edit_your_words(api, wordy, stranger) -> None:
    async with api as client:
        await sign_in(client, "intruder")
        response = await client.post(
            f"/api/artifacts/{wordy.id}/text",
            json={"changes": [{"index": 0, "text": "mine now"}]},
        )

    assert response.status_code == 404


# --- downloading a picture ----------------------------------------------


async def test_a_download_is_a_picture_by_default(api, artifact, monkeypatch) -> None:
    """A poster goes into a message, a feed or a noticeboard, and none of those
    take an HTML file."""
    import app.api.routes.artifacts as routes

    async def fake_png(html: str, *, width: int, height: int, scale: int = 2) -> bytes:
        assert "canvas" in html
        assert (width, height) == (794, 1123)
        return b"\x89PNG\r\n\x1a\nfake"

    monkeypatch.setattr(routes, "to_png", fake_png)

    async with api as client:
        await sign_in(client)
        response = await client.get(f"/api/artifacts/{artifact.id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == (
        'attachment; filename="Friday-night-jazz.png"'
    )
    assert response.content.startswith(b"\x89PNG")


async def test_a_deck_downloads_as_a_pdf(api, session, db_user, conversation, monkeypatch) -> None:
    """A poster goes on a noticeboard; a deck gets presented from and emailed."""
    import app.api.routes.artifacts as routes

    async def fake_pdf(html: str, *, width: int, height: int) -> bytes:
        assert (width, height) == (1600, 900)
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(routes, "to_pdf", fake_pdf)
    deck = await SqlArtifactRepository(session).create(
        conversation_id=conversation.id,
        user_id=db_user.id,
        message_id=None,
        kind="slides",
        title="Kopi",
        html=DOCUMENT,
        design_spec={"width": 1600, "height": 900},
    )

    async with api as client:
        await sign_in(client)
        response = await client.get(f"/api/artifacts/{deck.id}/download")

    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="Kopi.pdf"'


async def test_no_renderer_is_a_message_not_a_crash(api, artifact, monkeypatch) -> None:
    import app.api.routes.artifacts as routes
    from app.artifacts.raster import RasterUnavailable

    async def no_browser(html: str, *, width: int, height: int, scale: int = 2) -> bytes:
        raise RasterUnavailable("This deployment cannot export pictures.")

    monkeypatch.setattr(routes, "to_png", no_browser)

    async with api as client:
        await sign_in(client)
        response = await client.get(f"/api/artifacts/{artifact.id}/download")

    # A message, with the document still one query parameter away.
    assert response.status_code == 422
    assert "cannot export" in response.json()["error"]["message"]
