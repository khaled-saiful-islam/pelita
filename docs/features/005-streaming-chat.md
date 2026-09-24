# 005 — Streaming chat and server-side stop

## What it does

Sends a message, streams the answer token by token over SSE, and lets you stop
it. Stopping cancels generation on the server — not just in the browser — and
keeps whatever text had already arrived.

## How it works

### The event protocol

`POST /api/chat/stream` returns Server-Sent Events:

| event | payload | when |
|---|---|---|
| `start` | `conversation_id`, `user_message_id`, `assistant_message_id`, `title` | Once, before any token |
| `token` | `text` | Per chunk |
| `error` | `message` | A readable failure; the stream still ends with `done` |
| `done` | `finish_reason` — `stop` \| `stopped` \| `length` \| `error` | Always last |

Adding an event type is additive: a client that does not recognise one ignores
it. That is what let every later event arrive without a breaking change to
this contract, each documented with its feature:

| events | feature |
|---|---|
| `sources`, `images` | [011 — Web search](011-web-search.md), [017 — Images and citations](017-images-and-citations.md) |
| `usage` | [009 — Token and cost accounting](009-token-and-cost-accounting.md) |
| `suggestions` | [014 — Suggestions](014-suggestions.md) |
| `guard` | [015 — Prompt-injection guard](015-prompt-injection-guard.md) |
| `tool` | [020 — Tool calling](020-tool-calling.md) |
| `artifact.start` · `.step` · `.design` · `.plan` · `.part` · `.delta` · `.done` · `.failed` | [024 — Artifacts](024-artifacts.md) |

### A turn outlives the connection watching it

The turn runs in its own task, not inside the request that asked for it
(`app/services/live_turns.py`). What it emits goes into a buffer, and
connections subscribe: `POST /api/chat/stream` starts a turn and subscribes to
it, and `GET /api/chat/live/{conversation_id}` subscribes to one already
running, replayed from its first event — or answers 204 when nothing is. The
client asks on the way into every conversation, and retries a dropped
connection three times with a backoff. So a reload, a switch to another chat
or a flaky network mid-answer comes back to the whole answer, still arriving.
[024](024-artifacts.md#a-build-outlives-the-connection-watching-it) has the
detail, since a build of several minutes is where it matters most.

### Why the assistant row exists before the first token

`_begin_turn` writes the user message **and an empty assistant message** before
calling the model. The stop endpoint needs an id to address, and a reload
mid-stream should find the turn rather than a gap where it will be.

### Stopping actually stops

The browser aborting its `fetch` is not enough. Left alone, the server keeps
pulling tokens from the model and keeps being billed for them, and the partial
answer is lost.

So stopping is an explicit request:

1. `POST /api/chat/messages/{id}/stop` sets an `asyncio.Event` in the
   `CancellationRegistry`, after checking the caller owns the conversation.
2. The streaming loop checks that event between chunks and breaks.
3. Breaking closes the upstream `httpx` response, which is what actually stops
   generation.
4. The `finally` block persists the text collected so far with
   `finish_reason='stopped'`.

The frontend calls the endpoint **before** aborting its own fetch, for the same
reason — abort first and the server never hears about it.

Measured on a long generation: 187 tokens streamed, stop issued, 3 further
tokens arrived (the chunk already in flight), `done` reported `stopped`, and 635
characters were persisted.

### Transactions are short on purpose

A stream can stay open for minutes. Holding a database transaction for that long
pins a connection and blocks migrations for as long as someone is reading an
answer. So `ChatService` takes a session *maker*, not a session, and opens two
brief transactions — one to begin the turn, one to finish it. Nothing is held
open while tokens flow.

### Partial answers survive everything

The `finally` block persists whatever was collected whether the turn ended
normally, was cancelled, or raised. Text a user watched appear should still be
there after a reload; losing it because the provider died at token 400 is worse
than the failure itself.

### SSE framing uses CRLF

`sse-starlette` separates frames with `\r\n\r\n`. A parser matching only `\n\n`
finds nothing — and because the request still returns 200 and logs no error, the
symptom is an empty response rather than a parse failure. The reader in
`frontend/src/lib/sse.ts` accepts CRLF, LF and lone CR, and
`sse.test.ts` pins that behaviour.

`EventSource` is not used because it cannot POST or send a JSON body, both of
which this endpoint needs.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LLM_MAX_TOKENS` | `2048` | Response cap |
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature |
| `HISTORY_TOKEN_BUDGET` | `4096` | How much history reaches the prompt |

`MAX_MESSAGE_LENGTH` (32,000 characters) and `HISTORY_MESSAGE_LIMIT` (50) are
constants in `chat_service.py` rather than env vars — they are guard rails, not
preferences.

## How to extend it

- **A new stream event**: add a dataclass in `chat_service.py`, a case in
  `_to_sse`, and a case in the frontend's switch. Features 012 and 017 do
  exactly this.
- **Tool progress in the UI** (feature 014's "Searching the web…"): a `tool`
  event carrying `{tool, status, label}`, rendered as a disclosure row above the
  answer.
- **Regeneration**: delete the assistant message and re-run `stream_turn` with
  the same user message. Feature 008 does this.

## Known limits

- **One API worker.** `CancellationRegistry` is in-process, so a stop request
  arriving at a different worker than the stream would do nothing. Running
  `--workers 2` silently breaks the stop button. Lifting this means replacing
  the registry with a shared store keyed by message id — the class is three
  methods and nothing outside it knows how it works.
- **A live turn lives in one process.** The buffer a reconnect replays from is
  in memory, so with more than one API worker a reconnect must reach the
  worker running the turn, and a restart ends every turn in flight — each keeps
  the text it had written, but an artifact still being built is lost.
- **No streaming retry.** A provider failing at token 400 keeps those 400 tokens
  and reports the error; it does not restart.
- **History is a fixed window**, the newest 50 messages trimmed to the token
  budget. There is no summarisation of what falls out — that is a context
  contributor someone can add at order 250.

## Tests

`frontend/src/lib/sse.test.ts` — 9 tests: CRLF and LF framing, frames split
across chunks, a chunk boundary landing inside the separator, a multi-byte
character split across chunks, keep-alive comments, multi-line data, a trailing
frame with no blank line, and abort.

Verified end to end in a browser against ILMU: tokens rendered as they arrived,
markdown formatted, stop persisted a partial with `finish_reason=stopped`.
