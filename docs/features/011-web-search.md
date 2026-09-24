# 011 — Web search

## What it does

Searches the web when a question needs current information, tells you it is
doing so and why, reads the top pages it finds, feeds the results into the
prompt dated and ranked, and lists the sources under the answer. It knows what
today is, so "current" means now, not whenever the model was trained.

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
exchange. They are trimmed to `TOOLS_TOKEN_BUDGET` whole blocks at a time. When
the model called the tool itself, the same text (`format_results`) goes back as
the tool message.

### Current means now

Asked "who is the current EPL champion?" on 24 September 2026, Pelita answered
"Liverpool, 2024-25". Its own results said "2025/26: Arsenal". Asked the date,
it searched for "today" and found a TV show. Told it was wrong, it agreed with
whatever it was told. Each of those had a cause, fixed where it happened:

| What went wrong | Why | Now |
|---|---|---|
| Read 2025/26 as the future | Nothing said what today was | `ClockContributor` (order 150) gives the date, time and zone on every turn, and the arithmetic a model gets wrong: *2025 is over; 2025/26 has finished; 2026/27 is under way* |
| Searched for the date | Same | The note says never to; `search_intent` settles "what is the date?" without a search on the fallback path |
| Put a stale year in its query | It thinks it is still its training year | The tool description: short Google-style queries, never a year from memory, search again when results do not answer or disagree; an optional `recency` (day, week, month, year) |
| Could not tell old results from new | Every date was thrown away | Organic results keep Google's `date`; top stories arrive dated; pages read after the search give theirs, including when they were *updated*, so a Wikipedia list edited yesterday is not dated by the day it was created in 2006 |
| Missed the answer that was there | Only links and 400-character snippets were kept | Google's answer box, knowledge panel and sports card come first, as citable sources; the top three readable pages are opened and the passages that match the query attached |
| Chose the older of two answers | No rule said newer wins | `format_results` opens with the rules: newest dated source wins, say what date it is from, a page about an earlier season is history, results beat memory, say so rather than fill a gap |
| Caved when told it was wrong | A model's reflex is to agree | `DisputeContributor` (order 450, right before the message) when the message pushes back: do not concede, search, and say what the results show whoever that proves right. The same rule at the top of the prompt alone was ignored |

The browser sends its IANA zone with every turn (`timezone` on
`POST /api/chat/stream`), so "today" is the person's today; an unknown zone falls
back to `DEFAULT_TIMEZONE`.

### Reading the pages

`PageReader` (`tools/page_reader.py`) opens the first `SEARCH_READ_PAGES` results
worth opening, concurrently, each within `SEARCH_READ_TIMEOUT_SECONDS`. It skips
what a fetch gets nothing from — video, social networks, PDFs, Google itself —
and moves on to the next result, so the slots go to pages with text.

`page_text.py` pulls the words out with the standard library's HTML parser: the
article, its tables as `cell · cell · cell` rows, never scripts, menus or
footers (an article's own header is kept: it holds the headline and date), and
a label repeated down the page only once. Passages are chosen by overlap with
the query, plural-insensitive ("champion" finds "Current champions"), preferring
a sentence to a two-word label, up to 1,500 characters a page.

The chip says what is happening: *Searching the web* with the query, then
*Reading 3 pages* with the sites.

Every hop is checked before it is fetched: http(s) on ports 80 and 443 only,
and the host must resolve to public addresses — never loopback, the private
ranges, link-local (cloud metadata) or carrier-grade NAT; IP literals in any
notation are caught because the *resolved* addresses are checked. Redirects are
followed by hand, up to three, each checked the same way. Bodies stop at 1.5 MB,
and a compressed one is inflated by the reader itself, only as far as the room
left under the cap: transparent decoding inflates each chunk in full, and 16 KB
of a gzip bomb is 16 MB. Brotli is not asked for, and a page sent in it is not
read. What is read is scanned by the prompt-injection guard exactly like a
snippet: a page is the realistic injection vector, since nobody asked it for
instructions.

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
| `SEARCH_MAX_RESULTS` | `8` | Links fetched per search, besides Google's answers and top stories |
| `SEARCH_READ_PAGES` | `3` | Pages opened per search. `0` keeps to snippets |
| `SEARCH_READ_TIMEOUT_SECONDS` | `6` | Per page |
| `SEARCH_COUNTRY` | *(empty)* | Google's `gl`, e.g. `MY`. Empty lets Google guess, which from SerpAPI's servers usually means the US |
| `DEFAULT_TIMEZONE` | `UTC` | "Today" when the browser does not say where it is |
| `TOOLS_TOKEN_BUDGET` | `4096` | Ceiling on what reaches the prompt, per round |

Search mode is a per-browser preference, not a deployment setting.

## How to extend it

Swap providers by implementing `SearchProvider`:

```python
class BraveSearch(SearchProvider):
    name = "web_search"
    async def search(
        self, query: str, *, limit: int, recency: str | None = None
    ) -> list[ToolResult]: ...
```

One file, one line in `get_chat_service`. `ToolResultsContributor` is unchanged,
because it consumes `ToolResult` and has never heard of SerpAPI.

The same `tool`/`sources` event pair carries any future tool — a calculator, a
database lookup, a retrieval step — with no frontend change.

## Known limits

- **Pages that need JavaScript read as nearly empty.** The reader runs no
  scripts, so an app-shell page gives its title and little else; the snippet
  still stands.
- **DNS rebinding is not closed.** The address is checked, then connected to by
  name; a host that answers the check and the connection differently is not
  caught. Pinning the connection needs a custom httpx transport.
- **The fallback path searches the raw message.** A provider without function
  calling cannot write its own query, so it gets one search on what was typed.
- **Season arithmetic assumes the northern calendar.** Split-year seasons are
  taken to turn over in August, which is right for European football and most
  school years, not for every league.
- **The dispute check is by pattern**, in English, Malay and Chinese. Pushback
  phrased another way gets only the standing rule at the top of the prompt.
- **The model still writes the query.** A weak one sometimes writes a bad one;
  the answer then rests on the clock or says the results did not answer.
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

`backend/tests/test_search_results.py` — answer box, knowledge panel and sports
card kept and cited, top stories dated and capped, dates on organic results,
duplicates merged, contiguous ranks, `recency` to `tbs`, `gl` from the country,
and the tool dropping an invented recency.

`backend/tests/test_page_reader.py` — article kept and furniture dropped, dates
from meta, structured data and `<time>`, revision dates, repeated labels, the
passage that answers chosen (plural-insensitive, sentences over labels), only
readable pages read, ten private and reserved address shapes refused, odd ports
and schemes, a redirect into the network refused and one to a public page
followed, non-HTML and failing pages left as they were, the size cap, a gzip
page read, a 50 MB gzip bomb held under 10 MB of memory, brotli refused.

`backend/tests/test_clock.py`, `test_dispute.py`, `test_search_grounding.py` —
the date in the person's zone, paths refused as zones, the season arithmetic,
the dispute patterns (and "salah satu" not being one) and where the rule sits,
page text scanned by the guard, and the reported question driven through a
turn: the prompt carries the date and the tool message carries "published May
19, 2026" and the rules.

`backend/tests/test_search_intent.py` — 37 tests, plus the clock questions: twelve time-sensitive
questions settled by pattern with the model call asserted *not* to happen, ten
creative and code tasks skipped the same way, code blocks, the ambiguous middle
reaching the classifier, lenient reading of YES, anything-but-yes meaning no, no
classifier available, a failing classifier, and the reason naming the phrase
that triggered it.

## Verified

Before and after, the same questions through the UI against ILMU and SerpAPI on
24 September 2026:

| Question | Before | After |
|---|---|---|
| who is current EPL champion? | "Liverpool … 2024-25" | "Arsenal … won the 2025/26 title on May 19, 2026 [1][2]" |
| what is the current date? | Searched "today"; "I'm having trouble accessing that" | "Thursday, 24 September 2026", no search |
| you are completely wrong, the current champion is Liverpool | "You're absolutely right" | "You're mistaken … Wikipedia states 'Current champions Arsenal (2025–26)' [1]" |
| what is the latest iPhone model? | — | "iPhone 18 Pro and Pro Max, and the iPhone Duo … announced on September 9, 2026", citing apple.com |
| what time is it in London right now? | — | "9:48 AM … as of Thursday, September 24, 2026", after reading timeanddate.com and two others |

Earlier:

End to end against SerpAPI and ILMU. "What is the current weather in KL?" on
Auto searched on `mentions 'current'` and answered with live conditions;
"Write me a haiku about lanterns" and "Explain recursion" did not search; "Who
won the 2026 Malaysian general election?" and "What is the latest version of
Python?" did.
