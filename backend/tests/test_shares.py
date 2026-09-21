"""Public share links.

The bulk of this file is about what a stranger must *not* be able to see, which
is the only part of this feature that is hard to undo once it is wrong.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.core.security import hash_password
from app.db.models.conversation import Conversation, Message
from app.db.models.document import Document
from app.db.models.share import ConversationShare
from app.db.models.source import MessageSource
from app.db.models.user import User
from app.services.share_service import TOKEN_BYTES, ShareService


@pytest.fixture
async def conversation(session, db_user) -> Conversation:
    """A conversation with everything a message can carry, so the allow-list is
    tested against a fully-loaded row rather than an empty one."""
    record = Conversation(user_id=db_user.id, title="Nasi lemak research")
    session.add(record)
    await session.flush()

    question = Message(
        conversation_id=record.id, role="user", content="What is in nasi lemak?"
    )
    session.add(question)
    await session.flush()

    answer = Message(
        conversation_id=record.id,
        role="assistant",
        content="Rice cooked in coconut milk [1].",
        model="secret-internal-model-v9",
        finish_reason="stop",
        prompt_tokens=1234,
        completion_tokens=567,
        cost=Decimal("0.004200"),
        usage_source="provider",
    )
    session.add(answer)
    await session.flush()

    session.add(
        MessageSource(
            message_id=answer.id,
            tool="web_search",
            rank=1,
            title="Nasi lemak",
            url="https://example.test/nasi-lemak",
            snippet="A Malaysian dish.",
        )
    )
    session.add(
        Document(
            conversation_id=record.id,
            message_id=question.id,
            filename="recipe.txt",
            media_type="text/plain",
            size_bytes=42,
            text="SECRET: my grandmother's private recipe notes",
            unit="line",
            unit_count=3,
            token_count=12,
        )
    )
    await session.flush()
    return record


async def share_of(session, db_user, conversation) -> ConversationShare:
    return await ShareService(session).share(
        user_id=db_user.id, conversation_id=conversation.id
    )


# --- creating and revoking ----------------------------------------------


async def test_sharing_produces_an_unguessable_token(session, db_user, conversation) -> None:
    """The URL is the credential, so guessing must not be a strategy."""
    share = await share_of(session, db_user, conversation)
    # token_urlsafe(32) is 256 bits, which base64s to 43 characters.
    assert len(share.token) >= 40
    assert TOKEN_BYTES == 32


async def test_two_shares_do_not_collide(session, db_user, conversation) -> None:
    second = Conversation(user_id=db_user.id, title="Another")
    session.add(second)
    await session.flush()

    a = await share_of(session, db_user, conversation)
    b = await ShareService(session).share(user_id=db_user.id, conversation_id=second.id)
    assert a.token != b.token


async def test_a_conversation_has_one_link_not_many(session, db_user, conversation) -> None:
    """Otherwise every press of Share scatters a live URL nobody can enumerate
    or revoke."""
    first = await share_of(session, db_user, conversation)
    token = first.token
    again = await share_of(session, db_user, conversation)

    assert again.token == token
    rows = (
        await session.execute(
            select(ConversationShare).where(
                ConversationShare.conversation_id == conversation.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_resharing_picks_up_newer_messages(session, db_user, conversation) -> None:
    await share_of(session, db_user, conversation)
    session.add(
        Message(conversation_id=conversation.id, role="user", content="And sambal?")
    )
    await session.flush()
    await session.refresh(conversation)

    refreshed = await share_of(session, db_user, conversation)
    assert refreshed.message_count == 3
    assert any("sambal" in m["content"] for m in refreshed.snapshot)


async def test_revoking_makes_the_link_stop_resolving(session, db_user, conversation) -> None:
    share = await share_of(session, db_user, conversation)
    await ShareService(session).revoke(user_id=db_user.id, conversation_id=conversation.id)

    with pytest.raises(NotFoundError):
        await ShareService(session).view(share.token)


async def test_revoking_twice_is_not_an_error(session, db_user, conversation) -> None:
    """The caller wanted it gone and it is gone. Erroring only invites a retry."""
    await share_of(session, db_user, conversation)
    service = ShareService(session)
    await service.revoke(user_id=db_user.id, conversation_id=conversation.id)
    await service.revoke(user_id=db_user.id, conversation_id=conversation.id)


async def test_an_unshared_conversation_has_no_link(session, db_user, conversation) -> None:
    assert await ShareService(session).get(
        user_id=db_user.id, conversation_id=conversation.id
    ) is None


# --- ownership ----------------------------------------------------------


async def test_a_stranger_cannot_share_someone_elses_conversation(
    session, conversation
) -> None:
    with pytest.raises(NotFoundError):
        await ShareService(session).share(user_id=uuid4(), conversation_id=conversation.id)


async def test_a_stranger_cannot_revoke_someone_elses_link(
    session, db_user, conversation
) -> None:
    share = await share_of(session, db_user, conversation)
    with pytest.raises(NotFoundError):
        await ShareService(session).revoke(
            user_id=uuid4(), conversation_id=conversation.id
        )
    # Still live.
    assert (await ShareService(session).view(share.token)).title


async def test_a_missing_conversation_and_someone_elses_look_the_same(session) -> None:
    """So the endpoint cannot be used to discover which ids exist."""
    with pytest.raises(NotFoundError, match="No such conversation"):
        await ShareService(session).share(user_id=uuid4(), conversation_id=uuid4())


# --- what the public actually gets --------------------------------------


async def test_the_public_view_has_the_conversation(session, db_user, conversation) -> None:
    share = await share_of(session, db_user, conversation)
    public = await ShareService(session).view(share.token)

    assert public.title == "Nasi lemak research"
    assert public.message_count == 2
    assert [m["role"] for m in public.messages] == ["user", "assistant"]
    assert "coconut milk" in public.messages[1]["content"]


async def test_citations_survive_so_the_answer_stays_checkable(
    session, db_user, conversation
) -> None:
    share = await share_of(session, db_user, conversation)
    public = await ShareService(session).view(share.token)

    sources = public.messages[1]["sources"]
    assert sources[0]["url"] == "https://example.test/nasi-lemak"
    assert sources[0]["rank"] == 1


async def test_an_attached_file_shows_its_name_and_never_its_contents(
    session, db_user, conversation
) -> None:
    """The filename says a file was there. Its text is the user's document and
    was never the thing being shared."""
    share = await share_of(session, db_user, conversation)
    public = await ShareService(session).view(share.token)

    documents = public.messages[0]["documents"]
    assert documents[0]["filename"] == "recipe.txt"
    assert "text" not in documents[0]
    assert "grandmother" not in json.dumps(public.messages)


@pytest.mark.parametrize(
    "forbidden",
    [
        "1234",  # prompt_tokens
        "567",  # completion_tokens
        "0.004200",  # cost
        "secret-internal-model-v9",  # model
        "provider",  # usage_source
        "stop",  # finish_reason
    ],
)
async def test_the_owners_accounting_and_internals_are_not_published(
    session, db_user, conversation, forbidden
) -> None:
    """Billing, and a running inventory of which model a deployment runs."""
    share = await share_of(session, db_user, conversation)
    public = await ShareService(session).view(share.token)
    assert forbidden not in json.dumps(public.messages)


async def test_no_identifiers_are_published(session, db_user, conversation) -> None:
    """Nothing public should be addressable — an id invites trying it against an
    authenticated endpoint."""
    share = await share_of(session, db_user, conversation)
    public = await ShareService(session).view(share.token)

    body = json.dumps(public.messages)
    assert str(conversation.id) not in body
    assert str(db_user.id) not in body
    for message in public.messages:
        assert "id" not in message


async def test_the_snapshot_is_built_from_an_allow_list(
    session, db_user, conversation
) -> None:
    """A new column on `messages` must never publish itself. If this fails
    because a key was added on purpose, the question to answer is whether a
    stranger may read it."""
    share = await share_of(session, db_user, conversation)
    public = await ShareService(session).view(share.token)

    assert set(public.messages[0]) == {
        "role",
        "content",
        "created_at",
        "sources",
        "documents",
    }


# --- the snapshot is frozen ---------------------------------------------


async def test_messages_added_after_sharing_are_not_visible(
    session, db_user, conversation
) -> None:
    """The whole reason this is a copy. A filter hiding later messages is one
    bug away from not hiding them."""
    share = await share_of(session, db_user, conversation)
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content="my bank PIN is 1234, do not tell anyone",
        )
    )
    await session.flush()

    public = await ShareService(session).view(share.token)
    assert public.message_count == 2
    assert "bank PIN" not in json.dumps(public.messages)


async def test_editing_an_old_answer_does_not_change_what_is_public(
    session, db_user, conversation
) -> None:
    """Regenerating reuses the row, so a live view would silently republish."""
    share = await share_of(session, db_user, conversation)
    answer = (
        await session.execute(
            select(Message).where(
                Message.conversation_id == conversation.id, Message.role == "assistant"
            )
        )
    ).scalars().first()
    answer.content = "REPLACED after sharing"
    await session.flush()

    public = await ShareService(session).view(share.token)
    assert "REPLACED" not in json.dumps(public.messages)


async def test_deleting_the_conversation_takes_the_link_with_it(
    session, db_user, conversation
) -> None:
    """A live URL pointing at a deleted conversation is the worst failure this
    feature could have."""
    share = await share_of(session, db_user, conversation)
    await session.delete(conversation)
    await session.flush()

    with pytest.raises(NotFoundError):
        await ShareService(session).view(share.token)


# --- views are counted ---------------------------------------------------


async def test_views_are_counted_so_the_owner_can_see_it_is_live(
    session, db_user, conversation
) -> None:
    share = await share_of(session, db_user, conversation)
    service = ShareService(session)
    await service.view(share.token)
    await service.view(share.token)

    await session.refresh(share)
    assert share.view_count == 2
    assert share.last_viewed_at is not None


async def test_an_unknown_token_is_simply_not_found(session) -> None:
    """A revoked link and one that never existed give the same answer, so the
    endpoint cannot be used to learn which tokens are real."""
    with pytest.raises(NotFoundError, match="not available"):
        await ShareService(session).view("a-token-that-was-never-issued")


# --- through the API ----------------------------------------------------


@pytest.fixture
def api(session):
    from app.api.deps import get_session
    from app.main import create_app

    app = create_app()

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def sign_in(client, username="tester", password="hunter2hunter2"):
    response = await client.post(
        "/api/auth/signin", json={"identifier": username, "password": password}
    )
    assert response.status_code == 200, response.text


async def test_the_public_endpoint_needs_no_account(api, session, db_user, conversation):
    share = await share_of(session, db_user, conversation)
    async with api as client:
        # No cookie at all.
        response = await client.get(f"/api/shares/{share.token}")

    assert response.status_code == 200
    assert response.json()["title"] == "Nasi lemak research"


async def test_the_public_page_asks_not_to_be_indexed(
    api, session, db_user, conversation
):
    """Sharing a chat means "this person I sent it to", not "the web"."""
    share = await share_of(session, db_user, conversation)
    async with api as client:
        response = await client.get(f"/api/shares/{share.token}")

    assert "noindex" in response.headers["x-robots-tag"]
    assert response.headers["cache-control"] == "no-store"


async def test_a_revoked_link_is_gone_over_the_api(api, session, db_user, conversation):
    share = await share_of(session, db_user, conversation)
    async with api as client:
        await sign_in(client)
        await client.delete(f"/api/conversations/{conversation.id}/share")
        client.cookies.clear()
        response = await client.get(f"/api/shares/{share.token}")

    assert response.status_code == 404


async def test_sharing_over_the_api_returns_a_usable_link(api, db_user, conversation):
    async with api as client:
        await sign_in(client)
        response = await client.post(f"/api/conversations/{conversation.id}/share")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["url"].endswith(f"/s/{body['token']}")
    assert body["message_count"] == 2


async def test_another_signed_in_user_cannot_share_your_conversation(
    api, session, db_user, conversation
):
    intruder = User(
        username="intruder",
        email="intruder@example.com",
        password_hash=hash_password("hunter2hunter2"),
        is_active=True,
    )
    session.add(intruder)
    await session.flush()

    async with api as client:
        await sign_in(client, "intruder")
        response = await client.post(f"/api/conversations/{conversation.id}/share")

    assert response.status_code == 404


async def test_an_anonymous_user_cannot_create_a_share(api, conversation):
    async with api as client:
        response = await client.post(f"/api/conversations/{conversation.id}/share")
    assert response.status_code == 401


async def test_the_public_response_carries_no_unexpected_fields(
    api, session, db_user, conversation
):
    """The schema is the contract: anything not named in it cannot escape,
    whatever the snapshot happens to hold."""
    share = await share_of(session, db_user, conversation)
    async with api as client:
        response = await client.get(f"/api/shares/{share.token}")

    assert set(response.json()) == {"title", "messages", "shared_at", "message_count"}
