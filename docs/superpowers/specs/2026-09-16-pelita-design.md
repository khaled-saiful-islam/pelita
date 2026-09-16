# Pelita — Design

**Date:** 2026-09-16
**Status:** Approved

Pelita is an open-source chatbot template. Clone it, point it at any OpenAI-compatible
model, run `make up`. It is a template first and a product second: extensibility matters
more than feature count, so every pluggable part is a Protocol with a registry, and the
message array sent to the model is assembled by an ordered list of contributors rather
than by a function that knows about every feature at once.

Name: Pelita (Malay, "oil lamp"). Accent colour: amber `#F59E0B`.

## 1. Goals and non-goals

**Goals**

- One command to run everything, including migrations and an admin seed.
- Provider switching by editing `.env` only — no code change, no vendor SDK.
- Every feature documented in `docs/features/NNN-name.md` in the same commit.
- Adding a new context source (RAG, for example) is one new file plus one registry line.
- Degradation is always visible and never fatal to chat.

**Non-goals**

- Multi-tenancy, billing, or role hierarchies beyond a single admin flag.
- Horizontal scaling. The template runs one API worker; the places that assume this are
  documented with the change needed to lift the assumption.
- Vendor-specific features (function calling dialects, Anthropic-style tool blocks).

## 2. Stack

| Layer | Choice |
|---|---|
| API | FastAPI, Python 3.12, SQLAlchemy 2.0 async, Alembic, Pydantic v2 |
| Web | React 18, TypeScript, Vite, Tailwind, shadcn/ui |
| Store | PostgreSQL 16 |
| Run | Docker Compose + Makefile |

## 3. Repository layout

```
pelita/
├── Makefile                 up down logs migrate test lint reset dev seed
├── docker-compose.yml
├── .env.example             generic OpenAI defaults, committed
├── .env                     real credentials, gitignored
├── README.md
├── docs/
│   ├── features/NNN-name.md
│   └── superpowers/specs/
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/
│   └── app/
│       ├── main.py
│       ├── api/             HTTP only: routers, dependencies, request/response schemas
│       ├── services/        business logic; must not import fastapi
│       ├── providers/       base.py (Protocol), openai_compatible.py, demo.py, registry.py
│       ├── guards/          base.py (Protocol), prompt_injection.py, registry.py
│       ├── context/         base.py (Protocol), contributors, pipeline.py
│       ├── tools/           serpapi.py, news_mcp.py
│       ├── db/              models/, repositories/, session.py
│       └── core/            config.py, security.py, errors.py, logging.py
├── frontend/
│   ├── Dockerfile
│   └── src/
│       ├── styles/theme.css  every colour, radius and shadow — one file swaps the look
│       ├── components/{ui,chat,sidebar,news,settings}/
│       ├── hooks/  lib/  pages/
└── scripts/
```

### The layering rule is a test, not a convention

`backend/tests/test_layering.py` walks the AST of every module under `app/services/`,
`app/providers/`, `app/guards/` and `app/context/` and fails if any of them imports
`fastapi` or `starlette`. Conventions drift; a red test does not.

## 4. Provider adapter

```python
class LLMProvider(Protocol):
    name: str
    async def stream_chat(self, req: ChatRequest) -> AsyncIterator[StreamEvent]: ...
    async def complete(self, req: ChatRequest) -> Completion: ...
```

`OpenAICompatibleProvider` speaks raw `httpx` to `{LLM_BASE_URL}/chat/completions`. No
vendor SDK is used anywhere, which is what keeps the "any provider" claim honest — there
is no dependency that knows the name of a vendor.

`DemoProvider` replays recorded SSE chunks from `app/providers/recordings/`. Selected when
`DEMO_MODE=true`, so the repository is browsable with no API key at all.

`registry.get_provider(settings)` is the only place that decides between them.

Configuration is exactly three variables:

| Provider | `LLM_BASE_URL` | `LLM_MODEL` |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Ollama | `http://localhost:11434/v1` | `llama3.2` |
| OpenRouter | `https://openrouter.ai/api/v1` | `anthropic/claude-3.5-sonnet` |
| vLLM | `http://localhost:8000/v1` | the model you serve |
| ILMU | `https://api.ilmu.ai/v1` | `ilmu-v3.1` |

ILMU's gateway is already `/v1`-shaped, so it needs no special case. The local `.env` is
populated from `~/projects/ilmuchat/services/ai-service/.env` (`AIGW_BASE_URL`,
`AIGW_API_KEY`, `CHAT_MODEL`, `SERPAPI_KEY`) by a script that copies values without
printing them. `.env` is gitignored from the first commit.

## 5. The context pipeline

This is the central extensibility claim, so it gets the most care.

```python
@dataclass(frozen=True)
class TurnContext:
    conversation_id: UUID
    user_id: UUID
    user_message: str
    language: str | None
    history: tuple[StoredMessage, ...]
    tool_results: tuple[ToolResult, ...]
    guard_findings: tuple[GuardFinding, ...]
    budget: TokenBudget

class ContextContributor(Protocol):
    name: str
    order: int
    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]: ...
```

Registered contributors:

| order | contributor | budget |
|---|---|---|
| 100 | system prompt, plus the language directive | — |
| 200 | memory | `MEMORY_TOKEN_BUDGET` |
| 300 | tool results — search and news, guard-sanitised | `TOOLS_TOKEN_BUDGET` |
| 400 | history | `HISTORY_TOKEN_BUDGET` |
| 500 | the user message | — |

`build_messages()` sorts by `order`, calls each contributor, enforces per-contributor
budgets, and returns `(messages, BuildTrace)`. The trace records what each contributor
added and what was trimmed. That trace is what makes the template debuggable — without it,
"why did the model see that?" is answered by reading code instead of by reading output.

Adding retrieval later means one file at order 350 and one line in the registry. No
existing contributor changes, because none of them knows the others exist.

`TurnContext` is frozen and contributors return new lists, so a contributor cannot affect
what a later one sees except through its declared return value.

## 6. Guards

```python
class Guard(Protocol):
    name: str
    async def inspect(self, text: str, source: ContentSource) -> GuardVerdict

@dataclass(frozen=True)
class GuardVerdict:
    flagged: bool
    severity: Severity        # none | low | medium | high
    rules: tuple[str, ...]
    sanitized: str
```

`PromptInjectionGuard` inspects three sources — `user_input`, `web_search`, `news` — before
any of them reaches the prompt. Rule families: instruction override, role hijack, system
prompt exfiltration, delimiter injection, tool abuse phrasing, zero-width and homoglyph
obfuscation, long opaque base64 blobs.

When it fires the UI shows a banner naming the source and the rule family. The sanitised
text still flows, because a guard that silently eats the user's message is worse than one
that explains itself.

Tests ship both an attack corpus and a benign corpus. The benign corpus is the important
half: "how do I ignore case in a Python regex?" must not fire. A guard measured only
against attacks optimises into a keyword alarm.

## 7. Streaming and cancellation

SSE event types from API to browser:

```
start        {message_id, conversation_id}
guard        {flagged, severity, rules, source}
token        {text}
sources      {sources: [{title, url, snippet}]}
usage        {prompt_tokens, completion_tokens, cost, source}
suggestions  {items: [str, str, str]}
done         {finish_reason: stop | stopped | error}
error        {message}
```

Stop is `POST /conversations/{cid}/messages/{mid}/stop`. It sets an `asyncio.Event` in an
in-process `CancellationRegistry`. The streaming loop checks the event between chunks;
on cancellation it closes the upstream `httpx` response, persists the partial assistant
message with `finish_reason='stopped'`, and emits `done`.

The registry is in-process, which means one API worker. This is stated in
`docs/features/007-stop-and-cancel.md` along with the specific change required for
multi-worker deployment (a shared store keyed by message id). No unused abstraction is
built for a scaling need the template does not have.

## 8. Token and cost accounting

Usage is taken from the provider when it reports one (`stream_options.include_usage`),
and estimated with `tiktoken` when it does not. Every message records
`usage_source: 'provider' | 'estimated'`.

This distinction is load-bearing. Groq, Ollama and vLLM differ on whether they return
usage during streaming, and a cost table that silently mixes measured and guessed numbers
is a cost table that cannot be trusted. Pricing comes from
`LLM_PRICE_INPUT_PER_1M`, `LLM_PRICE_OUTPUT_PER_1M`, `LLM_PRICE_CURRENCY`.

Per-message totals roll up to a per-conversation total.

## 9. Language handling

`lingua-py`, restricted to English, Malay, Tamil, Chinese and Bengali. Restricting the
language set keeps the model small and sharply improves accuracy on short text, which is
what a first chat message usually is. Detection runs once on the first user message; the
result is stored on the conversation and the system prompt contributor turns it into a
reply-in-this-language directive.

Deterministic, free, and testable — an LLM classification call would cost money and tokens
on every new conversation and could not be asserted against in a unit test.

## 10. Tools

**Web search** — SerpAPI, triggered by an explicit toggle in the composer. Results pass
through the guard, become a `ToolResult`, and render as numbered sources under the answer.
An explicit toggle rather than intent detection: it is predictable, it is testable, and it
costs nothing when off. Intent detection can later be added as its own contributor.

**News strip** — `moltrus/google-news-mcp`, pinned at commit `a454db6295776f936146472d660c595f9b9449a1`,
reached through the official Python MCP SDK (`stdio_client` + `ClientSession`).

That server imports `mcp.server.fastmcp.FastMCP`, which exists only in `mcp<2`, while the
backend client uses `mcp` 2.x. Verified working: a 2.x client negotiates successfully with
a 1.x server over stdio. So the server is installed into its own virtualenv at
`/opt/mcp-news` with `mcp<2` pinned, and spawned by absolute path via `MCP_NEWS_COMMAND`.
The upstream `main()` also raises `ValueError` at teardown because it awaits a synchronous
`run()`; this happens after serving completes and is absorbed by the failure path below.

Responses cache in Postgres under a 30-minute TTL. Any MCP failure — spawn, protocol,
timeout, malformed payload — hides the strip and leaves chat untouched.

## 11. Data model

| table | purpose |
|---|---|
| `users` | id, email, username, password_hash, is_admin, display_name, timestamps |
| `conversations` | id, user_id, title, language, archived, timestamps |
| `messages` | id, conversation_id, role, content, finish_reason, model, prompt/completion tokens, cost, usage_source, suggestions (jsonb) |
| `message_sources` | id, message_id, title, url, snippet, rank |
| `message_feedback` | id, message_id, user_id, rating, reason |
| `memories` | id, user_id, content, source, enabled, timestamps |
| `news_cache` | id, cache_key, payload (jsonb), fetched_at, expires_at |
| `guard_events` | id, message_id, source, severity, rules (jsonb) |

## 12. Authentication

JWT access tokens, bcrypt password hashes. A seeded admin (`admin` / `admin` /
`admin@test.com`, overridable via `SEED_ADMIN_*`) exists so `make up` lands on a usable
app. The README carries an explicit warning to change it before any deployment, and the
seed is idempotent.

## 13. Error handling

Each degradation is contained and visible, and none of them breaks chat:

| failure | behaviour |
|---|---|
| MCP unavailable | strip hidden, chat unaffected |
| `SERPAPI_KEY` unset | search toggle disabled with an explanatory tooltip |
| guard fires | banner naming source and rules; sanitised text still flows |
| suggestions call fails | no chips rendered |
| provider 5xx or timeout | `error` event with a readable message; partial text retained |
| database unreachable | health check fails, container restarts |

## 14. Theming

`frontend/src/styles/theme.css` defines every colour, radius and shadow as CSS custom
properties on `:root`, overridden under `[data-theme="dark"]`. Tailwind consumes them as
`hsl(var(--token))`. Changing the entire look means editing that one file, which is the
point of shipping a template rather than an app.

The layout follows modern chat conventions — grouped conversation sidebar, centred message
column, sticky auto-growing composer, hover actions, streaming cursor — with its own name
and accent rather than an imitation of any existing product's branding.

## 15. Testing

| scope | tool |
|---|---|
| services, contributors, guards, providers | pytest + pytest-asyncio |
| API endpoints | httpx `ASGITransport` against a real Postgres |
| layering rule | AST walk over `app/services`, `app/providers`, `app/guards`, `app/context` |
| frontend units | Vitest + React Testing Library |
| critical flow | Playwright: login → chat → stop → export |

Target 80% coverage. The guard's benign corpus is treated as a first-class fixture, not an
afterthought.

## 16. Delivery

Twenty-one commits across eight phases. Every commit carries its feature document.

| phase | commits |
|---|---|
| Foundation | 001 provider adapter, 002 context pipeline, 003 docker + make |
| Auth | 004 auth/JWT, 005 profile |
| Core chat | 006 SSE streaming, 007 stop/cancel, 008 conversations |
| Chat UX | 009 layout + theme, 010 message actions, 011 markdown export, 012 feedback |
| Accounting + language | 013 token/cost, 014 language detection |
| Tools | 015 web search, 016 news strip |
| Memory + suggestions | 017 memory, 018 suggestions |
| Guard + polish | 019 injection guard, 020 demo mode, 021 settings |

The application runs at the end of every phase.
