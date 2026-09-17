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
| Search backends | `tools/serpapi.py` | built in `api/deps.py` |

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
200  memory
300  tool results
350  free — retrieval / RAG goes here
400  history
500  the user message
```

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

Target 80%. Currently ~84% backend.

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

- `sse-starlette` frames with **CRLF**; a parser matching `\n\n` found nothing
  while the request still returned 200.
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
```

Adding an event type is additive — a client that does not recognise one ignores
it. Add a dataclass in `chat_service.py`, a case in `_to_sse`, and a case in the
frontend switch.

`done` is always last. `usage` always arrives, including on cancellation and
error, because those tokens were still paid for.

## Known weak points

Be honest about these rather than discovering them:

- **`chat_service.py` is too big** (671 lines, `stream_turn` is 184). It
  orchestrates guards, search, images, context, streaming, accounting,
  suggestions and memory in one linear function. It wants a turn-step pipeline
  the way the prompt has a contributor pipeline. **This is the first thing to fix
  before adding agent/tool-calling features** — an agent loop cannot be bolted
  onto a strictly linear function.
- **There is no `Tool` protocol.** Search and news are called directly by name.
  Anything agentic needs tools to be enumerable and callable by the model, not
  pre-fetched by the service.
- **`useChat.ts` is 525 lines** with a ten-case switch — the same shape on the
  frontend.
- **JSON-array-from-model-prose parsing is duplicated** in `suggestion_service`
  and `memory_service`.
- **One API worker.** `CancellationRegistry` is in-process, so `--workers 2`
  silently breaks the stop button.
- **Pattern layers are English-only** — search intent, image intent, and the
  injection guard.

## Things that will look wrong but are deliberate

- **`usage_source`** distinguishes provider-reported from estimated token counts.
  Do not collapse it. Providers disagree about whether streaming carries usage,
  and a cost table that mixes measured and guessed numbers is worse than none.
- **Guard severity depends on the source.** A user telling their assistant to
  ignore its instructions is a preference; a web page saying it is an attack.
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
