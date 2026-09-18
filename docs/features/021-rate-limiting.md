# 021 — Rate limiting

## What it does

Caps how often one account can send messages or upload files, and how often one
address can try to sign in.

```
$ for i in $(seq 1 12); do curl -s -o /dev/null -w "%{http_code} " \
    -X POST localhost:8100/api/auth/signin -d '{"identifier":"x","password":"y"}'; done
401 401 401 401 401 401 401 401 401 401 429 429

HTTP/1.1 429 Too Many Requests
retry-after: 48
{"error":{"code":"rate_limited","message":"Too many requests. Try again in 48 seconds."}}
```

Before this there was none, anywhere. A template people deploy publicly with
their own API key in `.env` needs it more than most: one signed-in account
looping `/chat/stream` can spend the whole model budget before anyone notices.

## How it works

### Counted in Postgres, not in memory

An in-process counter is not a limit once there is more than one worker — it is
the limit multiplied by the worker count, which is the same shape of bug as
`CancellationRegistry` and just as quiet. One table, one row per
(bucket, identity, window):

```sql
INSERT INTO rate_limit_hits (bucket, identity, window_start, count) VALUES (…, 1)
ON CONFLICT (bucket, identity, window_start)
DO UPDATE SET count = rate_limit_hits.count + 1
RETURNING count
```

One statement, so two workers incrementing at the same instant cannot both read
the same value and write the same total. No Redis for a fork to run.

### Fixed windows

The window is derived from the clock (`_floor`), not from first use, so every
worker agrees where one begins without coordinating. Expired rows are swept
opportunistically — 1% of requests delete anything over an hour old — because a
template should not need a cron to stay correct.

The cost of fixed windows is that a burst straddling a boundary can briefly
reach twice the limit. For protecting an API budget that is a trade worth
making against storing a row per request.

### The count must survive the request failing

This is the part that was wrong first time and worth stating plainly.

A failed sign-in raises `AuthError`, `get_session` rolls the request back, and
the rate-limit increment rolled back with it — so ten thousand wrong passwords
counted as zero. **The endpoint most worth limiting was the one endpoint with no
limit at all**, and everything looked fine: the table stayed empty, and nothing
errored.

`check()` now commits the increment immediately, before the request does
anything else. It is found by hammering the running app, which is the only way
it shows up; there is now a test that does the same thing through the ASGI app.

### Who is being counted

| bucket | counted per | default | why |
|---|---|---|---|
| `chat` | user | 20/min | Each request can become several model calls |
| `upload` | user | 10/min | Extraction and a vision call cost real money |
| `auth` | client address | 10/min | These are reached before anyone is signed in |

Chat and upload use the user id, which is the honest identity once someone has
signed in. Auth has no user yet, so it uses the address — which needs care.

### Reading the address is a security decision

nginx sets `X-Forwarded-For $proxy_add_x_forwarded_for`, which **appends** the
real peer to whatever the client sent. So a request arriving as
`X-Forwarded-For: 1.2.3.4` reaches the API as `1.2.3.4, 203.0.113.9`.

The **last** entry is the one nginx added, and the only one worth believing.
Reading the first — the usual mistake — would let anyone reset their own limit
by sending a header with a fresh fake address on every attempt, which makes the
limit decorative.

`TRUST_PROXY_HEADERS=false` ignores the header entirely and uses the socket
peer. That is the right posture when the API is exposed without a proxy in
front, where the header is wholly client-controlled.

### Applied as dependencies, not middleware

```python
@router.post("/stream", dependencies=[Depends(limit_chat)])
```

Middleware would have to map routes to buckets and dig the user out of the
request itself. A dependency says which limit applies right where the route is
declared, and the limit runs before the endpoint body — so a refused request
costs a row update, not a model call.

## Configuration

| variable | default | what it does |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | `false` disables all of them |
| `RATE_LIMIT_CHAT_PER_MINUTE` | `20` | Messages per user |
| `RATE_LIMIT_UPLOAD_PER_MINUTE` | `10` | File uploads per user |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | Sign-in, sign-up and password change, per address |
| `TRUST_PROXY_HEADERS` | `true` | `false` when nothing trustworthy sits in front |

`0` on any individual limit means unlimited, so one bucket can be switched off
without disabling the rest.

Defaults are deliberately generous — a person typing quickly will not reach 20
messages a minute, and someone scripting a loop will. Tighten them for a public
deployment.

## How to extend it

**A new bucket** — a setting, and one dependency next to the others in
`deps.py`. `RateLimiter.check(bucket, identity, Limit(n, seconds))` takes any
window, not just a minute.

**Per-plan limits** — `Limit` is constructed by the dependency, so it can come
from the user row rather than from settings. That is exactly how the per-user
token quota in [022](022-user-management.md) works.

**Redis instead** — implement the same `check()` signature against Redis and
swap it in `deps.py`. Postgres is the default because it is already there.

## Known limits

- **Fixed windows, not sliding.** A burst across a boundary can reach roughly
  twice the limit for a moment.
- **A refused request still costs a database round trip.** Cheap next to a model
  call, but not free — a determined flood is still work.
- **`chat` is counted per request, not per token.** Twenty short messages and
  twenty long ones count the same; the token quota is the answer to that.
- **The sweep is probabilistic.** On a very quiet instance old rows can sit for
  a while. They are tiny and the index is on `window_start`.
- **Nothing limits an unauthenticated request to an endpoint that needs auth** —
  it is rejected by the auth check first, which is cheaper anyway.
- **One nginx hop is assumed.** Behind two proxies the last entry is the inner
  proxy, not the client.

## Tests

`backend/tests/test_rate_limit.py` — 19 tests:

- **Windows** derived from the clock, at a minute and at five minutes.
- **Counting**: under the limit passing, one over refused, the refusal carrying
  a usable `retry_after`, identities counted separately, buckets counted
  separately, an earlier window not counting against this one, and the count
  actually stored where another worker would see it.
- **Switches**: disabled counting nothing, a zero limit meaning unlimited, an
  empty identity not counted — otherwise every unidentifiable caller shares one
  bucket and the first few lock out the rest.
- **Address**: the last hop trusted behind a proxy, the header ignored without
  one, the peer as fallback, `unknown` rather than empty when there is no peer
  at all, and a 500-character header truncated to fit the column.
- **Through the ASGI app**: twelve failed sign-ins producing exactly ten 401s
  then 429s — the regression test for the rollback bug — and the 429 carrying
  `Retry-After` and the right error code.

## Verified

Twelve sign-in attempts against the running app: ten `401`, then `429` with
`Retry-After: 48` and the standard error envelope. The counter row was visible
in Postgres with the caller's real address, forwarded by nginx.
