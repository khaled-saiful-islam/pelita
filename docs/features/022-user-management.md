# 022 — User management and token quotas

## What it does

Two ways an account comes into existence, and one way it stops being able to
spend money.

| | |
|---|---|
| **Sign-up** | Anyone, at `/signup`. This already existed |
| **Admin creates it** | `/admin` — username, email, password, optional admin flag, optional token cap |
| **Admin disables it** | Sign-in refused, and any live session dies on its next request |
| **Admin caps it** | Tokens per rolling 24 hours. Unlimited by default |

```
Users                                              [+ New user]

demo            demo · demo@pelita.local        Make admin   Disable
Used in 24h: 15,167    Limit: 500

Administrator  [Admin]  admin · admin@test.com  Remove admin  Disable
Used in 24h: 25,694    Limit: unlimited
```

## How it works

### The admin guard is a dependency

```python
AdminUser = Annotated[User, Depends(current_admin)]
```

Every route in `api/routes/admin.py` takes it. A check written inside each
handler is a check someone forgets on the one route that matters — and the
route where it is forgotten is never the harmless one.

An anonymous request gets `401`, a signed-in non-admin gets `403`. Both are
tested, because collapsing them into one status is how "not signed in" ends up
being reported as "you are not allowed", which sends people to the wrong fix.

### Disabling takes effect immediately, not at the next sign-in

`AuthService.get_user` already refused inactive accounts, which means a disabled
user's existing cookie stops working on their very next request. Nothing had to
be added for that, and it is the behaviour you want: disabling somebody who is
mid-session and waiting until their token expires is not disabling them.

### Two things that cannot be done, ever

- **You cannot disable or demote yourself.**
- **You cannot disable or demote the last active administrator.**

A single-admin install is the normal case for this template. An admin who
removes their own access has no way back in short of a database console, and
"the template let me lock myself out" is not a bug report anyone should have to
file. A *disabled* admin is no cover for this — they cannot sign in either, so
they do not count toward the total.

Both rules live in the service, not the UI. The buttons are greyed out too, but
that is only so nobody is offered a control whose single outcome is an error.

### The quota is a rolling 24 hours

Summed from the messages themselves:

```sql
SELECT sum(prompt_tokens + completion_tokens)
FROM messages JOIN conversations ON …
WHERE conversations.user_id = :user AND messages.created_at >= now() - interval '24 hours'
```

From the messages rather than a counter, so it stays true when a conversation is
deleted and there is nothing to keep in step.

**Rolling**, not "since midnight". A daily reset has a moment at which a blocked
account unblocks and the entire next allowance can go in an hour; a rolling
window frees up gradually as old messages age past 24 hours. It is also what
someone reading "used in the last 24 hours" already expects.

`NULL` is unlimited and is the default for every account, including every
account that existed before this shipped. A template that throttles by surprise
is worse than one that does not throttle; an admin who wants a cap sets one.
`0` is a real limit that stops an account entirely — it is not "unlimited"
spelled differently.

### Checked before the turn, never during it

The quota runs in the same dependency as the chat rate limit, in cost order:
how often this account may ask, then how much it may spend. Both before the
endpoint body, so a refusal costs a query rather than a model call.

**A turn is never cut off part-way.** Someone with a hundred tokens left gets a
whole reply and ends slightly over. Stopping mid-sentence to save a fraction of
a cent is a worse product than being approximate about the ceiling.

### Rate limit and quota are different controls

They are often confused and both are needed. Twenty short messages and twenty
long ones pass the same *rate* limit and cost very different money; one enormous
message passes the rate limit every time. The quota is about spend, the rate
limit about frequency.

Both raise `RateLimitError` and surface as `429`, because to a client they are
the same shape of answer: not now, here is why, here is when.

### The refusal reaches the user

The chat stream's failure path used to say "The server refused the request
(429)" — throwing away the body at exactly the moment it matters. It now reads
the error envelope, so the chat shows:

> You have used your 500-token allowance for the last 24 hours (15,167 used).
> It frees up as older messages age out.

`GET /api/auth/me/usage` lets a signed-in user see their own figures, so a cap
is visible rather than a surprise at the moment it bites. Its own endpoint
rather than a field on `/me`, because it costs a query and every page load asks
who you are.

## Configuration

Nothing to configure. Limits are per account, set by an administrator, and
default to unlimited.

The seeded `admin` account from `make up` is the administrator to start with —
which is one more reason `SEED_ADMIN_PASSWORD` must change before this is
exposed anywhere. The app already refuses to start with the shipped default when
`APP_ENV=production`.

## How to extend it

**Deleting accounts** — deliberately absent. Disabling keeps the conversations,
the accounting and the audit trail; deleting raises what happens to all of it,
which is a policy question a template should not answer for a fork. The service
is where it would go.

**Different windows** — `TokenQuota.WINDOW` is one constant. A per-account
window would be another column, read the same way the limit is.

**Cost limits instead of token limits** — `messages.cost` is already stored per
message, so the same query summed over a different column gives a currency cap.

**Invitations instead of open sign-up** — the admin create endpoint is most of
it; add a token and turn the sign-up route off.

## Known limits

- **The quota query scans a user's recent messages** on every turn. An index on
  `conversations.user_id` ships with the migration, which keeps it to the rows
  that matter, but a very heavy account is a growing scan. A cached counter is
  the answer if that ever bites.
- **A turn can finish over the limit**, by design. The overrun is at most one
  reply.
- **No usage history.** You can see the last 24 hours, not a chart over time.
- **No self-service password reset.** An admin can set a password; there is no
  email flow, because that needs a mail provider a template should not assume.
- **Accounts cannot be deleted** through the UI or the API.
- **Sign-up cannot be switched off**, so "admin-only accounts" is not yet a
  configuration.
- **Disabling does not end an in-flight stream.** It takes effect on the next
  request; a response already streaming finishes.

## Tests

`backend/tests/test_admin_and_quota.py` — 34 tests:

- **The quota**: no limit meaning unlimited, usage summing prompt and
  completion, over the limit refused, exactly at the limit refused, usage older
  than 24 hours falling out, usage at 23 hours still counting, one user's
  spending not counting against another, and the refusal naming both figures.
- **Creating**: username and email lowercased, the password hashed so the
  account can actually sign in, duplicate username and email as conflicts, a
  short password and a negative limit refused.
- **Changing**: disabling, setting a limit, clearing it explicitly, zero as a
  real limit, an admin resetting a password, and a missing user as not-found.
- **Lockout**: you cannot disable or demote yourself; the last active
  administrator cannot be disabled or demoted; a second admin makes the first
  removable; a *disabled* admin is no cover for the last active one.
- **Through the ASGI app**: a normal user getting 403 and an anonymous one 401,
  an admin creating a user, disabling one, a disabled user then failing to sign
  in, a user reading their own allowance, and a user over their limit getting
  429 before any model call.

The lockout tests use a `sole_admin` fixture that first deactivates every other
administrator — the database these run against contains the seeded `admin`
account, so a test about "the last one" has to make that true rather than assume
it.

## Verified

Against the running app as the seeded admin: the list showed real 24-hour usage
per account (demo 15,167, admin 25,694), self-row buttons were disabled, and
setting demo's limit to 500 took effect immediately. Signed in as demo,
`/api/auth/me/usage` reported `{used: 15167, limit: 500, remaining: 0}` and a
chat attempt returned `429` with `Retry-After: 3600` — rendered in the chat as
the full explanation rather than a status code.
