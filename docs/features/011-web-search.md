# 011 — Web search

## What it does

An explicit Search toggle in the composer. When on, Pelita runs a SerpAPI search
before answering, tells you it is doing so, feeds the results into the prompt,
and lists the sources under the answer.

## How it works

### An explicit toggle, not intent detection

Guessing when a question needs the web means either a classifier call on every
message or a keyword heuristic that is wrong in both directions. A toggle is
predictable, costs nothing when off, and is trivially testable.

Intent detection remains available as a later addition — it would be a service
that flips `use_search`, with nothing else changing.

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

### The toggle reflects reality

`/api/config` reports `search_enabled`, which is simply whether `SERPAPI_KEY` is
non-empty. With no key the toggle renders disabled with a tooltip naming the
variable, instead of offering a button that always fails.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SERPAPI_KEY` | *(empty)* | From serpapi.com. Empty disables the toggle |
| `SERPAPI_BASE_URL` | `https://serpapi.com/search` | Override for a proxy |
| `SEARCH_MAX_RESULTS` | `5` | Results fetched per search |
| `TOOLS_TOKEN_BUDGET` | `2048` | Ceiling on what reaches the prompt |

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
- **No result caching.** Asking the same question twice costs two searches.
- **Citation quality depends on the model.** The prompt asks for `[n]` markers;
  a weaker model may cite loosely or not at all.
- **SerpAPI's free tier is small.** A 429 surfaces as "Search quota exhausted."

## Tests

`backend/tests/test_tools.py` — result parsing and ranking, skipping malformed
results rather than failing, snippet truncation, limits, the four HTTP error
classes, timeouts, the missing-key message, and the contributor's numbering,
citation instruction, budget trimming and order.

## Verified

End to end against SerpAPI and ILMU: tool events rendered, five sources
collected and persisted, and the answer cited them inline.
