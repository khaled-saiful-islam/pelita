# 023 — Public share links

## What it does

Turn a conversation into a read-only link anyone can open without an account.

```
Share this chat
Anyone with this link can read this chat. They do not need an account,
and they cannot reply or see anything else of yours.

http://localhost:8100/s/jhkFBB7eic_cQWJac3TCuRafKzQvhVzmElZ9lpOyiEM   [Copy]

It shows the 2 messages as they were when you shared — anything said
since stays private until you update it.

[Update to latest]  [Stop sharing]                              [Done]
```

The public page renders with the same markdown and citation components as the
real chat, so a shared answer reads identically — but there is no sidebar, no
composer and nothing to click through to.

## How it works

Two decisions carry the security. Both are the boring option, chosen because
this is the one feature in the app where a mistake is *public*.

### 1. A snapshot, not a live view

A public reader never touches the conversation. Sharing copies the messages into
`conversation_shares.snapshot`, and the public endpoint reads only that.

The alternative — reading live messages with a `WHERE created_at <= shared_at`
filter — is one bug away from not filtering. A copy written before those
messages existed cannot leak them however wrong the query is.

It buys three things beyond that:

- **What the owner reviewed is what is public**, permanently. Nothing they say
  afterwards joins it by surprise.
- **Regenerating an old answer does not silently republish.** Regeneration
  reuses the same row, so a live view would change what strangers read.
- **Revoking is deleting one row**, with nothing to invalidate elsewhere.

Verified rather than assumed: with a link live, a message containing `SECRET`
was added to the conversation; the shared copy still reported two messages and
the string appeared nowhere in the response.

### 2. Fields are copied in, never filtered out

`_public_message()` names every field a stranger may see. Everything else is
absent *by construction* — including fields that do not exist yet, which is the
point. A deny-list gets this backwards and fails silently the first time the
schema grows.

| in | out, and why |
|---|---|
| `role`, `content`, `created_at` | **ids** — nothing public should be addressable, and an id invites trying it against an authenticated endpoint |
| `sources` — so the answer stays checkable | **cost, token counts, `usage_source`** — the owner's billing |
| `documents`: filename, unit, thumbnail | **`model`** — a running inventory of what a deployment runs |
| | **`finish_reason`** — internal state |
| | **feedback, guard findings** — the owner's private opinion of an answer, and a map of what trips the injection guard |
| | **attached file *contents*** — the filename says a file was there; its text is the user's document and was never the thing being shared |

There is a test asserting the exact key set of a public message. If it fails
because a key was added deliberately, the question to answer is whether a
stranger may read it.

The response model is a second, independent gate: `PublicConversationResponse`
names four fields, so nothing can escape through it whatever the snapshot holds.

### The token is the credential

`secrets.token_urlsafe(32)` — 256 bits, 43 characters. At a million guesses a
second this outlives the sun. It is stored in plaintext, like every capability
URL (Dropbox, Google Docs, Calendly): it has to be shown back to the owner, and
it grants read access to content they chose to make readable.

One link per conversation. Pressing Share twice refreshes the snapshot and keeps
the token, so a link already sent keeps working and picks up the rest of the
chat. Anyone who wants the old link dead revokes it — a different intent, with
its own button.

### The public endpoint

`GET /api/shares/{token}` is the only unauthenticated route in the app that
returns anyone's content. It carries:

- **`X-Robots-Tag: noindex, nofollow, noarchive`.** Sharing a chat means "this
  person I sent it to", not "the web". It costs nothing and is the difference
  between a private link and a published page.
- **`Cache-Control: no-store`.** Nothing is personalised, but it is somebody's
  conversation, and a shared cache holding it is not a risk worth taking.
- **Its own rate-limit bucket**, per address. Separate from `auth` so a popular
  shared link cannot lock its readers out of signing in.

A revoked token and one that never existed give the same 404, so the endpoint
cannot be used to learn which tokens are real.

### Ownership, and what happens on delete

Sharing, reading and revoking all go through `repo.get(id, user_id)` — ownership
as a parameter of the lookup, not a check the caller must remember. A signed-in
stranger asking to share your conversation gets the same "no such conversation"
as someone using a random id. Verified: an **admin** account gets 404 too, since
admin rights are over accounts, not over other people's chats.

Both foreign keys are `ON DELETE CASCADE`. Deleting the conversation — or the
account — takes the public link with it. A live URL pointing at a deleted
conversation is the worst failure this feature could have.

## Configuration

| variable | default | what it does |
|---|---|---|
| `PUBLIC_BASE_URL` | *(empty)* | Where shared links point. Empty falls back to the request |
| `RATE_LIMIT_SHARE_PER_MINUTE` | `60` | Public reads per address |

**Set `PUBLIC_BASE_URL` for any real deployment.** The fallback builds the link
from the incoming request, which behind a proxy is whatever the proxy forwarded.

That fallback exposed a genuine bug: nginx shipped with
`proxy_set_header Host $host`, which **drops the port**, so every link came out
as `http://localhost/s/…` and did not resolve. It now forwards `$http_host`.
That header is client-controlled, which is acceptable only because the link is
shown back to the requester alone — and is the reason `PUBLIC_BASE_URL` exists.

## How to extend it

**Expiring links** — a nullable `expires_at`, checked in `view()`. The token
lookup is the one place that decides whether a link resolves.

**Password-protected links** — a hash on the row and a body on the public
request. The snapshot design means the gate is the only thing to add.

**"Continue this chat"** — a public reader forking the conversation into their
own account. The snapshot is already exactly the right payload to copy from.

**Showing who shared it** — deliberately absent. It is the one thing that would
add PII to a public page, and the recipient already knows who sent them a link.

## Known limits

- **A copied link cannot be un-copied.** Revoking stops the URL resolving; it
  does not reach anyone who already read the page. This is true of every share
  link and worth saying out loud.
- **No expiry.** A link lives until revoked or the conversation is deleted.
- **No per-link analytics beyond a view count** and a last-viewed timestamp — no
  referrers, no addresses. Deliberate: the page is somebody's conversation, not
  a marketing funnel.
- **The snapshot duplicates message text.** Storage roughly doubles for a shared
  conversation. Negligible next to the safety it buys.
- **`view_count` is best-effort.** It is incremented in a wrapped statement, so
  a counter failure can never turn a working link into an error page.
- **Images inside a shared answer are hotlinked**, exactly as in the chat, so
  they rot the same way.
- **Thumbnails of uploaded images are included.** Sharing a chat shares the
  pictures in it — but never the extracted text of a document.

## Tests

`backend/tests/test_shares.py` — 33 tests, mostly about what must *not* escape:

- **Creating and revoking**: an unguessable token, no collisions, one link per
  conversation, re-sharing picking up newer messages, revoking stopping
  resolution, revoking twice not erroring, an unshared conversation having none.
- **Ownership**: a stranger cannot share or revoke someone else's conversation,
  and a missing conversation looks identical to someone else's.
- **What the public gets**: the conversation and its citations; an attached
  file's name but never its contents; parametrised checks that cost, token
  counts, model, `usage_source` and `finish_reason` appear nowhere; no ids at
  all; and the exact key set of a public message.
- **Frozen**: messages added after sharing invisible, an edited old answer not
  republished, deleting the conversation taking the link with it.
- **Through the ASGI app**: the public endpoint working with no cookie, the
  `noindex` and `no-store` headers, a revoked link 404ing, a share response
  whose URL matches its token, another signed-in user refused, an anonymous
  create refused, and the response carrying no unexpected fields.

## Verified

End to end against the running app. A link created from the chat header opened
signed-out with the conversation, its ten sources and its citation chips, and
nothing else. Adding a message to the live conversation left the shared copy at
two messages with no trace of it. An admin account attempting to share another
user's conversation got 404. Revoking returned 204, after which the link
returned 404 and the page read *"This link is not available. It may have been
revoked."*
