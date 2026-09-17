# 011 — Web search

## What it does

Searches the web when a question needs current information, tells you it is
doing so and why, feeds the results into the prompt, and lists the sources under
the answer.

## How it works

### Three modes

| mode | behaviour |
|---|---|
| **Auto** (default) | Decides per message whether the question needs the web |
| **Always** | Searches every message |
| **Off** | Never searches |

The choice persists in `localStorage`. A preference that resets on reload is not
a preference — the first version of this feature was a plain toggle that reset
on every page load, which meant "what is the current weather in KL?" answered
from training data and looked broken.

### Auto-detection is two stages, cheapest first

Most messages are obvious in either direction:

- **"Needs current information"** patterns — weather, news, prices, *latest*,
  *today*, *who won*, *still maintained* — search immediately, no model call.
- **"Never needs it"** patterns — *write me a*, *translate*, *refactor*,
  *calculate*, or any fenced code block — skip immediately, no model call.
- **Everything else** gets one cheap classification call capped at four output
  tokens.

Classifying every message with an LLM would add a round trip to "write me a
haiku" for no benefit. Classifying none of them is what caused the bug above.

A failing classifier means no search, never a failed turn.

### The reason is shown

The decision carries why it fired, and the tool row displays it:

```
Searching the web · mentions 'current'
Searched the web · 5 results
```

Auto-detection that cannot explain itself looks like the app searching at
random, and the first thing someone does with behaviour they cannot predict is
switch it off.

### The user is told what is happening

A search adds several seconds before the first token. Without saying so, the app
looks stalled. Three `tool` SSE events cover the states:

```
{"tool":"web_search","status":"running","label":"Searching the web","detail":"<query>"}
{"tool":"web_search","status":"done","label":"Searched the web","detail":"5 results"}
{"tool":"web_search","status":"failed","label":"Search unavailable","detail":"<reason>"}
```

The UI renders these as a row above the answer: a pulsing globe with shimmering
text while running, a tick and the result count when done.

### A failed search degrades, never blocks

`SearchUnavailable` is caught inside the turn. The model answers from what it
knows, and the UI shows a failed row. Losing search should cost you freshness,
not the answer.

### Results reach the model through a contributor

`ToolResultsContributor` at order 300 formats results as numbered blocks and
instructs the model to cite them inline as `[1]`, `[2]`. That instruction is what
makes the source list correspond to the text above it.

Order 300 puts them after standing context and before history, so the model reads
them as the most recently established facts rather than as part of an old
exchange. They are trimmed to `TOOLS_TOKEN_BUDGET` whole blocks at a time.

### Sources are persisted

`message_sources` rows are written with the answer, so citations survive a
reload. An answer you cannot check is worth less than one you can. Regenerating
replaces them wholesale rather than accumulating.

### The control reflects reality

`/api/config` reports `search_enabled`, which is simply whether `SERPAPI_KEY` is
non-empty. With no key the control renders disabled with a tooltip naming the
variable, instead of offering a button that always fails. `always` is also
resolved through the same check, so a missing key is a no-op rather than an
error to understand.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SERPAPI_KEY` | *(empty)* | From serpapi.com. Empty disables the toggle |
| `SERPAPI_BASE_URL` | `https://serpapi.com/search` | Override for a proxy |
| `SEARCH_MAX_RESULTS` | `5` | Results fetched per search |
| `TOOLS_TOKEN_BUDGET` | `2048` | Ceiling on what reaches the prompt |

Search mode is a per-browser preference, not a deployment setting.

## How to extend it

Swap providers by implementing `SearchProvider`:

```python
class BraveSearch(SearchProvider):
    name = "web_search"
    async def search(self, query: str, *, limit: int) -> list[ToolResult]: ...
```

One file, one line in `get_chat_service`. `ToolResultsContributor` is unchanged,
because it consumes `ToolResult` and has never heard of SerpAPI.

The same `tool`/`sources` event pair carries any future tool — a calculator, a
database lookup, a retrieval step — with no frontend change.

## Known limits

- **Snippets only.** Pelita does not fetch page bodies, so answers are limited to
  what the search engine summarises.
- **One search per turn**, on the raw user message. No query rewriting and no
  follow-up searches.
- **Auto-detection patterns are English only.** A Malay or Chinese question
  about today's weather falls through to the classifier call rather than being
  caught by pattern.
- **The classifier can be wrong in both directions.** Always and Off exist for
  when it is.
- **No result caching.** Asking the same question twice costs two searches.
- **Citation quality depends on the model.** The prompt asks for `[n]` markers;
  a weaker model may cite loosely or not at all.
- **SerpAPI's free tier is small.** A 429 surfaces as "Search quota exhausted."

## Tests

`backend/tests/test_tools.py` — result parsing and ranking, skipping malformed
results rather than failing, snippet truncation, limits, the four HTTP error
classes, timeouts, the missing-key message, and the contributor's numbering,
citation instruction, budget trimming and order.

`backend/tests/test_search_intent.py` — 37 tests: twelve time-sensitive
questions settled by pattern with the model call asserted *not* to happen, ten
creative and code tasks skipped the same way, code blocks, the ambiguous middle
reaching the classifier, lenient reading of YES, anything-but-yes meaning no, no
classifier available, a failing classifier, and the reason naming the phrase
that triggered it.

## Verified

End to end against SerpAPI and ILMU. "What is the current weather in KL?" on
Auto searched on `mentions 'current'` and answered with live conditions;
"Write me a haiku about lanterns" and "Explain recursion" did not search; "Who
won the 2026 Malaysian general election?" and "What is the latest version of
Python?" did.
