# 020 — Tool calling

## What it does

The model is handed the tool list and decides what to run, how many times, and
with what arguments — instead of a regex deciding for it.

Asking two questions at once now does two searches:

```
You:   What is the current weather in Kuala Lumpur, and who is the prime
       minister of Malaysia right now?

       ✓ Searched the web · 5 results in 1.2s
       ✓ Searched the web · 5 results in 1.4s

Bot:   Current Weather in Kuala Lumpur: 27°C, some clouds with rain expected…
       Prime Minister of Malaysia: Anwar Ibrahim, the 10th, since 2022 [6][7]
       10 sources
```

The old path could only run one tool, chosen from English keywords in the
question. This one reads the question the way the model does.

## How it works

### The seam that was already there

`Tool` has carried `description` and `parameters` since it was written, and
`_select_tool` was five lines with a docstring saying to replace it. This
feature is that replacement. No tool changed. `tool_schema()` builds the wire
format from the protocol's own fields, so a tool becomes model-callable by
existing — there is no schema registry to keep in step.

### The loop

`_generate` is now one loop rather than one call:

```
assemble prompt (+ the tool exchange so far)
stream the model, with tools attached
    no tool calls  → that was the answer, done
    tool calls     → run them, append the exchange, go round again
```

Without tool calling `remaining` starts at zero, nothing is offered, and it is a
single streamed pass — byte for byte what it was before.

Each round appends two things to `state.exchange`, which is replayed on every
later iteration:

| message | why |
|---|---|
| `assistant` with `tool_calls` | What the model asked for. Dropping it makes the tool result answer a question nobody asked |
| `tool` with `tool_call_id` | What came back. An unanswered call id is a protocol error on the very next request |

**Every branch appends a tool message**, including the failures — unknown tool,
malformed JSON, no usable argument. "I could not do that" has to be said in the
exchange, not only in the log, or the next request is rejected outright.

### Streamed calls arrive in pieces

Arguments come a few characters per chunk and are useless until complete, so the
provider accumulates them by index and emits one `ToolCallsEvent` when the
stream ends. A caller reassembling fragments would be doing the provider's job.

Three things that bite here, all handled in `_absorb_call_fragment`:

- Only the **first** fragment carries the id and name; the rest are argument
  text.
- Some providers **omit `index`** for a single call. Defaulting to 0 rather than
  auto-incrementing is what stops one call per chunk.
- A fragment with **no function name** is dropped. It cannot be dispatched, and
  an empty name would be reported as an unknown tool rather than the provider
  bug it is.

### Results go in as tool messages, not twice

When the model chose the tool, `tool_results` is withheld from `TurnContext`:
the results are already in the exchange where the protocol puts them, and
passing both would send every page to the model twice.

The citation numbering and the "cite these as [1], [2]" instruction live in one
function, `format_results()`, used by both paths — a system message when the
turn chose, a tool message when the model did. One copy, so the two cannot
drift.

### Two searches, one numbering

Both searches come back numbered from 1. `TurnState.absorb()` renumbers each
batch to follow what is already there, so a turn with two rounds has sources
1–10 and `[2]` means one page rather than two.

The frontend had the matching bug: `onSources` replaced rather than appended, so
the second batch wiped the first and `[3]` pointed at nothing while `[8]`
pointed into a list of five. `mergeSources()` merges by rank. A second run of the
same tool also gets its **own chip** now — two searches are two things that
happened, and collapsing them hid the second one's results entirely.

### Usage is summed

A turn that called a tool paid for two model calls, and a two-round turn paid
for three. `TurnState.add_usage()` sums rather than replaces; reporting only the
last call priced a turn at a third of what it cost.

Mixing a measured count with an estimated one degrades the whole turn to
`estimated`, for the same reason `usage_source` exists at all.

### Search mode still means something

| mode | what the model gets |
|---|---|
| `off` | No tools at all, and no pattern fallback either |
| `auto` | Tools, `tool_choice: "auto"` |
| `always` | Tools, `tool_choice: "required"` — on the first pass only |

Forcing on the first pass only matters: leaving it on makes the model call again
forever instead of answering from what it just got.

### When the provider cannot

Not every endpoint does function calling. Two protections:

1. **A rejected `tools` payload** (400/404/422 mentioning tools or functions)
   disables it for the process, sets `supports_tools=False`, and retries. What
   is lost is the model's *choice*, not the tool — the turn falls back to
   `_select_tool` and still searches.
2. **Tool calls that were never offered are ignored.** Otherwise the iteration
   cap is advisory: a provider that always calls something could loop as long as
   it liked.

`_select_tool` is therefore kept, not deleted. A local Ollama build with no
function calling should still search, and a template that only works against the
big providers is not much of a template.

### Dispatch resolves by the tool's own name

`_tools_to_offer()` re-keys the registry by `tool.name`, because that is what
the schema advertises and therefore what the model calls back with. The
registry's key is usually the same string — dispatch must not depend on that.

## Configuration

| variable | default | what it does |
|---|---|---|
| `TOOL_CALLING_ENABLED` | `true` | `false` forces the pattern path |
| `TOOL_MAX_ITERATIONS` | `3` | Rounds of tool calls per turn |

`TOOL_MAX_ITERATIONS` is the cost ceiling as much as the loop guard: each round
is another model call. Three rounds is four calls worst case.

## How to extend it

**A new tool** — unchanged from before: one file implementing `Tool`, one line
in `tools/registry.py`. It is now model-callable the moment it exists.

**Better descriptions** — `description` and `parameters` are the whole of what
the model knows. A vague description is why a tool does not get called.

**Parallel dispatch** — calls in one round run in sequence today. `_dispatch` is
the one place to change; results are already keyed by call id.

**A tool that needs more than one string** — `first_argument()` takes the first
declared parameter. A multi-argument tool wants its own unpacking, and
`parameters` already describes the shape.

## Known limits

- **One round runs its calls in sequence.** Two searches in one round are two
  round trips, not one.
- **`first_argument()` is a single-string convention.** It tolerates a model
  returning `q` instead of `query` — pedantry there costs an answer — but a tool
  wanting structured arguments has to unpack them itself.
- **Preamble text before a tool call is kept.** A model that says "Let me look
  that up." and then calls a tool leaves that sentence in the answer.
- **`tool_choice: "required"` is not universal.** Providers spell forcing
  differently; `always` degrades to "offered" on one that does not know it.
- **No per-tool timeout.** A slow tool holds the turn; only the provider's own
  timeout applies.
- **The cap is a count of rounds, not of spend.** Three rounds of a tool
  returning large results is a large prompt, three times.
- **Fallback is all-or-nothing per process.** One rejected payload disables tool
  calling until restart, even if it was a transient 400.

## Tests

`backend/tests/test_tool_calling.py` — 27 tests: schema generation, argument
extraction including the wrong-key case, fragment assembly (joined arguments,
a missing index, two concurrent calls, a nameless fragment dropped, index
ordering), and the loop itself — the model choosing, the chip showing the
chosen query, tools offered with their schema, `always` forcing once and only
once, `off` offering nothing, the exchange replayed, results not sent twice,
renumbering across rounds, usage summed, the cap holding, unknown tools and
malformed arguments answered rather than ignored, two calls in one round both
answered, and both fallback paths.

`backend/tests/test_tool_protocol.py` — every protocol claim is now
**parametrised over both paths**, patterns and model. "The service never names a
tool" has to hold on each, and the two disagree about registry keys, which is
exactly why dispatch re-keys on `tool.name`.

`frontend/src/lib/chat-events.test.ts` — sources merged across rounds and sorted
by rank, a repeated rank replaced rather than duplicated, a running chip updated
in place, and a second run getting its own chip.

## Verified

Against `ilmu-v3.1`: *"What is the current weather in Kuala Lumpur, and who is
the prime minister of Malaysia right now?"* produced **two** searches, two
chips, 10 sources numbered 1–10, and an answer citing [6] and [7] correctly —
without a single keyword rule involved.

Two bugs were found by running it in a browser rather than in tests, both
documented above: sources replaced instead of merged, and — separately —
`index.html` was being cached by nginx, so a deploy changed the bundle names
while every browser kept asking for the old ones. Both are fixed.
