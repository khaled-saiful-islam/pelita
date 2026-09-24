# Working on Pelita

Guidance for Claude Code and other AI assistants working in this repository.
Read this before writing code here.

## What this is

A chatbot **template**. People clone it and change it. That single fact decides
most arguments: extensibility beats features, clarity beats cleverness, and a
thing someone has to understand before they can change it must be small enough
to hold in your head.

## Run it

```bash
make up      # build, migrate, seed, start, print the login — from a clean clone
make dev     # hot reload on both sides
make test    # backend pytest with coverage, then frontend vitest
make lint    # ruff over the backend, tsc over the frontend
```

Docker is the only prerequisite. `make test` and `make lint` run the frontend
toolchain in a container.

**Do not** `docker compose restart api` after editing Python — the image bakes
the source. Use `make api-dev` (mounts the working tree, reloads on save) or
rebuild.

## The three rules that actually matter

### 1. Logic never imports FastAPI

`services/`, `providers/`, `guards/`, `context/`, `tools/` and `core/` hold
logic. `api/` holds HTTP. `backend/tests/test_layering.py` walks the AST and
fails the build if that drifts. If you need the request object in a service, you
have designed it wrong — pass the values in.

### 2. Everything pluggable is a Protocol plus a registry

| thing | protocol | registry |
|---|---|---|
| Model backends | `providers/base.py` | `providers/registry.py` |
| Guards | `guards/base.py` | `guards/registry.py` |
| Prompt sources | `context/base.py` | `context/registry.py` |
| Tools | `tools/base.py` | `tools/registry.py` |
| Artifact kinds | `artifacts/base.py` | `artifacts/registry.py` |
| Search backends | `tools/serpapi.py` | used by the tools above |
| File readers | `services/document_extract.py` | `classify()` |
| Vision backends | `vision/base.py` | `vision/registry.py` |

Adding one is a new file plus one registry line. If your change requires editing
three existing files, stop and ask whether the seam is in the wrong place.

### 3. Failure degrades, it never breaks the turn

Every optional thing — memory, search, news, suggestions, guards, extraction —
is wrapped so a failure produces a worse answer, not a failed request. Look at
`_memories_for` or `NewsService.headlines` for the shape. A bare `except` in
this codebase is usually correct and should carry a comment saying why.

## The prompt is built by contributors

This is the central design idea. `context/pipeline.py` sorts contributors by
`order`, calls each one, and concatenates the result.

```
100  system prompt
150  the date and time (`context/clock.py`)
200  memory
300  tool results
350  attached files — the retrieval slot (`context/documents.py`)
400  history
450  a challenge to the last answer (`context/dispute.py`)
500  the user message
```

Document upload is the proof that this works: it landed as one contributor plus
one registry line, with no branch added to the turn. A real retriever replaces
that contributor at the same order without touching anything else.

To put something new in front of the model, write a class with `name`, `order`
and `contribute()`, and add one line to `context/registry.py`. Do not add
branches to `chat_service.py` for it.

`TurnContext` is frozen. Contributors cannot see each other's output, so the
prompt is a pure function of the turn plus the registry order.

`build_messages()` returns a `BuildTrace` — use it when asking "why did the model
see that?".

## Conventions

- **Python 3.12**, `from __future__ import annotations` at the top of every
  module, full type annotations on signatures.
- **Frozen dataclasses** for anything crossing a boundary. Mutating shared state
  is the bug you will spend a day on.
- **`ruff`** with the config in `pyproject.toml`. Line length 100.
- **TypeScript strict.** No `any`; use `unknown` and narrow.
- **Tailwind against theme tokens only.** Never a literal colour in a component —
  `frontend/src/styles/theme.css` is the single source, and a fork restyles the
  whole app by editing it.

## Testing

Target 80%. Currently 85% backend, across 1177 backend and 117 frontend tests.

- Service tests use **fakes, not mocks** (`tests/fakes.py`, `FakeProvider` in
  `test_chat_service.py`). Asserting on call arguments tests the wiring; these
  tests are about behaviour.
- Integration tests use a **rollback-per-test Postgres fixture** (`conftest.py`).
  No test cleans up after itself.
- The prompt-injection guard ships an **attack corpus and a benign corpus**. The
  benign one is the harder half — a guard that fires on "how do I ignore case in
  a regex?" gets switched off, and a guard that is off catches nothing. Add to
  both when you touch a rule.

### Bugs that only appear in a browser

Three real ones shipped past curl and unit tests. Check the browser console
before claiming a feature works:

- **A rate-limit increment rolled back with the request that failed.** Anything
  counted on a path that then raises must commit itself, or the endpoint most
  worth limiting is the one with no limit. `RateLimiter.check` commits.
- `sse-starlette` frames with **CRLF**; a parser matching `\n\n` found nothing
  while the request still returned 200.
- **A failed `docker compose build web` leaves the old image running.** The
  browser then shows behaviour you already fixed. `make lint` type-checks the
  app; `npm run build` also type-checks the tests, so a bad test file fails the
  deploy and not the lint.
- **nginx must forward `Host $http_host`, not `$host`.** `$host` drops the
  port, so any URL the API builds from the request came out as
  `http://localhost/…` and did not resolve. `PUBLIC_BASE_URL` is the real fix
  for a deployment; the header is client-controlled.
- **`index.html` must never be cached.** It names the hashed bundles, so a
  cached copy pins the whole app to an old deploy while the new one sits there
  being served to nobody.
- Calling `request.is_disconnected()` inside an SSE generator puts a second
  reader on the ASGI receive channel and corrupts the close handshake.
- Images rendered while streaming and vanished on reload, because the restore
  path is a different code path from the stream path. **Reload the page.**

## Adding a feature

1. A feature document in `docs/features/NNN-name.md` in the same commit, covering
   what it does, how it works, its configuration, how to extend it, and its
   **known limits**. The limits section is not optional — it is what stops the
   next person rediscovering a constraint the hard way.
2. New settings go in `core/config.py` **and** `.env.example`, with a comment.
3. A migration for schema changes. Add `server_default` when adding a NOT NULL
   column, or it fails on every existing install. Use `clock_timestamp()`, never
   `now()` — `now()` is the transaction start time and is identical for rows
   written together, which makes `ORDER BY created_at` unstable.
4. Tests for the behaviour, including the failure path.
5. `make lint && make test` before committing.

## Streaming protocol

SSE events from `/api/chat/stream`:

```
start · guard · tool · images · sources · token · usage · suggestions · done · error
artifact.start · artifact.step · artifact.design · artifact.plan · artifact.part
artifact.delta · artifact.done · artifact.failed
```

A turn runs in its own task, not in the request (`services/live_turns.py`);
connections subscribe to its buffer. `GET /api/chat/live/{conversation_id}`
rejoins one still running, replayed from its first event, or answers 204.

Adding an event type is additive — a client that does not recognise one ignores
it. Add a dataclass in `services/events.py`, a case in `_to_sse`, and a case in
`lib/chat-events.ts` plus a handler in `useChat`.

On the frontend the wire format lives in `lib/chat-events.ts`, the shapes in
`lib/chat-types.ts`, and `useChat` says only what each event *means* for the
conversation.

`done` is always last. `usage` always arrives, including on cancellation and
error, because those tokens were still paid for.

## Artifacts

An artifact is **one self-contained HTML document** — a poster, a slide deck, a
game, a website or an app. Not a component and not a template plus data: a
document is the only format the browser, the printer, the share link and the
download all already understand, which is why this feature adds no service and no
dependency.

A *kind* owns its prompt, its canvas and its sandbox policy, and declares the
last of those itself. A poster is static art, so the frame it renders in cannot
execute a script; the same `SandboxPolicy` drives the iframe attribute and the
CSP header, so the preview, a new tab and a shared link cannot disagree about
what a document may do. A game, a website and an app run scripts; a website
also answers its own forms; an app also remembers, in `artifact_states` (one
row per artifact per user). The ones that run are used in a real browser
(`playtest.py`, `sitetest.py`, `apptest.py`) before anyone sees them.

The chat model writes a **brief** and never code. A separate model with its own
budget directs, composes, is validated and refines. Feature notes and the known
limits are in `docs/features/024-artifacts.md`.

## A turn has four phases

`ChatService.stream_turn` is deliberately short. It calls four phases, each of
which yields events and records into a mutable `TurnState`:

```
_open      persist the question, reserve a row for the answer
_prepare   guards, tool selection, tool execution
_generate  assemble the prompt and stream the model
_close     persist what arrived; then _follow_up for suggestions and memory
```

No function in `app/` exceeds 50 lines. Keep it that way — if a phase is growing,
it wants splitting, not another `if`.

## Adding a tool

Implement `Tool` (`tools/base.py`) and add one line to `tools/registry.py`:

```python
class WeatherTool(Tool):
    name = "weather"
    description = "Look up the current weather somewhere."   # a model reads this
    parameters = text_parameter("query", "Where to look up the weather")
    presentation = ToolPresentation(
        running="Checking the weather", done="Checked the weather", noun="reading"
    )
    async def run(self, **kwargs) -> Sequence[ToolResult]: ...
```

A tool is handed **every argument it declared** and nothing else — `bind_arguments`
drops what the model invented, and keeps the near-miss rescue (`q` for `query`)
for tools with exactly one required parameter, filled only from a key the tool
never declared. A missing required argument is reported by name
rather than as "no usable argument", because the model can only fix a call it
understands.

A tool whose work takes tens of seconds implements `stream` instead (subclass
`StreamingTool`), yielding `Progress` and `Results` as it goes. The service
checks for that by shape — `isinstance(tool, ProgressiveTool)` — never by name,
which is the same rule that decides an image result from its `thumbnail_url`.

`ChatService` never names a tool except in `_select_tool`, which is the single
place selection happens. `backend/tests/test_tool_protocol.py` adds a tool the
codebase has never heard of and asserts it runs, labels itself and fails
gracefully — so the claim is checked, not asserted.

**The model already chooses.** `_generate` loops: stream → tool calls → run →
stream again, capped by `TOOL_MAX_ITERATIONS`. `_select_tool` survives as the
fallback for providers without function calling, and is used when
`TOOL_CALLING_ENABLED=false` or a `tools` payload is rejected.

Things to keep true when changing the loop:

- **Every tool call gets a tool message**, failures included. An unanswered
  `tool_call_id` is a protocol error on the next request.
- **Calls that were not offered are ignored**, or the iteration cap is advisory.
- **Usage sums across rounds.** A two-round turn paid for three model calls.
- **Results are renumbered** as they arrive (`TurnState.absorb`), so two
  searches do not both produce a `[1]`.
- **`tool_results` is withheld from `TurnContext`** on the model path — they are
  already in the exchange, and passing both sends every page twice.

Results with a `thumbnail_url` render as an image grid; results without render
as citations. That is decided by shape, not by tool name, so a new tool that
returns pictures gets the grid for free.

## Known weak points

Be honest about these rather than discovering them:

- **One API worker.** `CancellationRegistry` is in-process, so `--workers 2`
  silently breaks the stop button.
- **Pattern layers are English-only** — search intent, image intent, and the
  injection guard.
- **One round's calls run in sequence**, not in parallel. `_dispatch` is the
  one place to change that.
- **Fallback is per process.** One rejected `tools` payload disables tool
  calling until restart, even if the 400 was transient.
- **Document retrieval is keyword scoring**, not embeddings. It misses synonyms:
  a question about "notice period" does not rank a paragraph headed
  "Termination" any higher unless the word appears. Deliberate — it needs no
  vector store and no indexing step — but it is the ceiling of the approach, and
  order 350 is designed so a real retriever can replace it.
- **Attached files are re-sent every turn** and cost `DOCUMENTS_TOKEN_BUDGET`
  each time. No excerpt caching between turns.
- **Extraction is synchronous.** A 5 MB PDF holds its request for a second or
  two, and an image upload holds it for the length of a vision call.
- **Images inside documents are invisible.** Only a file that *is* an image
  gets a vision call; a photo inside a PDF or docx is not extracted.
- **Uploaded images are not safety-screened.** The hook belongs in
  `_read_image()` between `prepare()` and `reader.read()`, so one check covers
  every path to the model. Fine locally; not fine facing the public internet.

## Things that will look wrong but are deliberate

- **`usage_source`** distinguishes provider-reported from estimated token counts.
  Do not collapse it. Providers disagree about whether streaming carries usage,
  and a cost table that mixes measured and guessed numbers is worse than none.
- **Guard severity depends on the source.** A user telling their assistant to
  ignore its instructions is a preference; a web page saying it is an attack.
- **Uploads are stored as extracted text, not as bytes.** No object storage to
  configure, and a bad PDF fails once at upload rather than inside a chat turn.
  The cost is that the original cannot be shown back or re-parsed later.
- **An uploaded image is read once, at upload, into text.** It then travels
  the document path unchanged — same column, same budget, same contributor,
  same card. The alternative is multimodal `ChatMessage.content`, which stops
  being a `str` and pushes that shape into every contributor and the token
  counter for one feature. The cost is that the transcript is fixed at upload,
  which is why the prompt transcribes exhaustively rather than answering.
- **`documents.message_id` is nullable, and that is the state model.** Null
  means "still in the composer", set means "a card in the transcript". A file is
  uploaded before there is a message to bind it to, so the gap is real rather
  than an oversight. `_begin_turn` binds pending files in the same transaction
  that saves the question, which is what stops the composer and the transcript
  disagreeing after a reload. The limit counts every file, not the pending ones.
- **The document budget is split evenly across files**, not first-come.
  Otherwise one long file consumes it and a question about the third is answered
  from nothing, with no way for the user to see why.
- **The news MCP server runs in its own virtualenv** at `/opt/mcp-news` pinned to
  `mcp<2`, while the client uses `mcp` 2.x. Verified to interoperate over stdio.
- **Costs use `Decimal` and six decimal places.** A 40-token reply costs
  $0.000006; two places reports every short message as free.
- **Search is `auto` by default** and explains itself (`mentions 'current'`).
  Behaviour nobody can predict is behaviour people switch off.

## Security

- `.env` is gitignored and has never been committed. Keep it that way.
- The app **refuses to start** when `APP_ENV=production` and the JWT secret is
  still the shipped default.
- Session tokens live in an httpOnly cookie, never in a response body or
  `localStorage`.
- Failed sign-in returns one message for both "no such user" and "wrong
  password". Do not make it more helpful.
- Ownership is a **parameter of the lookup** (`repo.get(id, user_id)`), not a
  check the caller must remember. Keep it that way in new repositories.
- **Rate limits are counted in Postgres**, not in memory, so they hold across
  workers. Chat and uploads per user, auth per address.
- **Admin routes take `AdminUser`**, a dependency — never an `if user.is_admin`
  inside a handler. The route where that gets forgotten is never a harmless one.
- **An admin cannot disable or demote themselves, or the last active admin.**
  A single-admin install is the normal case here, and there is no way back in.
- **Token quotas are summed from `messages`, over a rolling 24 hours**, not from
  a counter — so they stay true when a conversation is deleted. Checked before
  the turn; a turn already running is never cut off part-way.
- **A shared conversation is a frozen copy, and its fields are an allow-list.**
  `_public_message()` names what a stranger may see; anything unnamed — including
  a column added later — is absent by construction. A deny-list fails silently
  the first time the schema grows. There is a test asserting the exact key set.
- **The public share endpoint is the only unauthenticated route returning
  content.** It carries `noindex` and `no-store`, has its own rate-limit bucket,
  and answers a revoked token exactly as it answers one that never existed.
- **`X-Forwarded-For`: read the LAST hop, never the first.** nginx appends the
  real peer to whatever the client sent, so the first entry is attacker-supplied
  and trusting it makes any per-address limit decorative.
