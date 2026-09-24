# 002 — Context pipeline

## What it does

Builds the message array sent to the model from an ordered list of independent
contributors, instead of from one function that knows about every feature at
once. Adding a new source of prompt content — retrieval, a user's calendar, a
compliance preamble — is a new file and one line in a registry. No existing
contributor changes, and neither does the code that calls the model.

This is the piece that makes Pelita a template rather than an app.

## How it works

A contributor implements one method:

```python
class ContextContributor(Protocol):
    name: str
    order: int
    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]: ...
```

`build_messages()` sorts contributors by `order`, calls each one, concatenates
what they return, and records a trace. It knows nothing about memory, history or
tools — it sorts, calls, measures and records.

`TurnContext` is a frozen dataclass. A contributor cannot mutate the turn and
cannot see what another contributor produced, so the prompt is a pure function of
the turn plus the registry order. That is what makes contributors testable in
isolation and reorderable without surprises.

### Ordering

Values are spaced so a new contributor slots between two existing ones without
renumbering anything:

| order | contributor | added by |
|---|---|---|
| 100 | system prompt | 002 |
| 150 | the date and time, and what they rule out | 011 |
| 200 | memory | 013 |
| 300 | tool results — search | 011 |
| 350 | attached files — the retrieval slot | 018 |
| 400 | history | 002 |
| 450 | a challenge to the last answer, when there is one | 011 |
| 500 | user message | 002 |

### The trace

`build_messages()` returns `(messages, BuildTrace)`. The trace records how many
messages and tokens each contributor added, and names any that failed.

This exists because the most common question when a model behaves oddly is "what
did it actually see?" Without a trace that is answered by reading code and
guessing. With one it is answered by reading output.

### Failure is contained

A contributor that raises is logged, recorded in the trace as `name (failed)`,
and skipped. The turn continues.

Losing retrieved documents or memory should degrade an answer, not destroy it. A
vector store timing out must not turn a working chat into a 500. The trace entry
is what keeps the degradation visible instead of silent.

### Trimming

`trim_to_budget()` drops whole messages until the list fits, never partial ones.
Half a truncated exchange reads to the model as a conversation that did not
happen, which produces worse output than simply having less history.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SYSTEM_PROMPT` | see `config.py` | Opens every prompt |
| `MEMORY_TOKEN_BUDGET` | `512` | Ceiling for the memory contributor (017) |
| `TOOLS_TOKEN_BUDGET` | `2048` | Ceiling for tool results (015, 016) |
| `HISTORY_TOKEN_BUDGET` | `4096` | Ceiling for conversation history |

## How to extend it

Adding retrieval, end to end:

```python
# app/context/contributors.py
class RetrievalContributor(ContextContributor):
    name = "retrieval"
    order = 350

    def __init__(self, store: VectorStore) -> None:
        self._store = store

    async def contribute(self, ctx: TurnContext) -> list[ChatMessage]:
        hits = await self._store.search(ctx.user_message, limit=5)
        if not hits:
            return []
        body = "\n\n".join(h.text for h in hits)
        return [system(f"Relevant context:\n\n{body}")]
```

```python
# app/context/registry.py — one line
return (
    SystemPromptContributor(settings.system_prompt),
    RetrievalContributor(store),      # <-- added
    HistoryContributor(),
    UserMessageContributor(),
)
```

That is the whole change. `test_new_contributor_slots_in_without_touching_others`
in the test suite asserts this works, so the claim is checked rather than
asserted in prose.

If a contributor needs data `TurnContext` does not carry, add a field to it with
a default. Existing contributors ignore it.

## Known limits

- **Contributors run sequentially.** Two that each make a network call add their
  latencies. Running them concurrently is a change to `build_messages()` alone,
  but it is not worth the complexity until a deployment actually has two slow
  contributors.
- **Budgets are per contributor, not global.** Every contributor spending its
  full budget can exceed a small context window. The model reports the overflow;
  Pelita does not pre-empt it. A global ceiling would need a trimming policy
  across contributors, which is a decision the template should not make for you.
- **`order` collisions are resolved arbitrarily.** Two contributors with the same
  value sort unpredictably. The spacing convention exists to avoid this.
- **The trace is not persisted.** It goes to logs. Storing it per message would
  make prompt archaeology possible and is a reasonable extension.

## Tests

`backend/tests/test_context_pipeline.py` — registry ordering independent of
argument order, trace contents, failure containment, a new contributor slotting
in at 350, empty contributions omitted, history trimming oldest-first, blank
message skipping, zero and negative budgets, never splitting a message, and
`TurnContext` immutability.

`backend/tests/test_layering.py` — walks the AST of every module under
`services/`, `providers/`, `guards/`, `context/`, `tools/` and `core/` and fails
if any imports `fastapi` or `starlette`. Conventions drift; a red test does not.
