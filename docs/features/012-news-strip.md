# 012 — News strip

## What it does

A briefing across the top of the new-chat screen, chosen from what you have
been asking about. One story leads at a time, set large, in a card tinted by its
source, and the next turns in every few seconds with the next three waiting
beside it. Every story can become a conversation: **Ask Pelita about this**
writes the headline into the box. Pulled from an MCP server, cached in Postgres
for 30 minutes. If anything fails, the briefing is hidden and chat is untouched.

### Why a briefing and not a row of cards

A strip of six identical grey cards, above the composer and then at the top of
the screen, read as something that had wandered in from another page, and
nothing on it asked to be touched. So:

- **One story at a time.** A serif headline, its source and when; the card's
  tint drifts to each source's colour as the stories turn (`--hue` is a
  registered property, so it eases rather than snaps). The current story's dot
  stretches and fills while it leads.
- **The next three are beside it**, and choosing one makes it the lead.
- **Pointing at it, or tabbing into it, holds the story showing.** With reduced
  motion it never turns on its own.
- **Ask Pelita about this** is the point of news in a chat app. It writes
  "Tell me more about this story from ...: <headline>" into the box without
  sending, because they may want to ask something narrower.
- **Dates read like dates.** Recent is relative ("3h ago"); past a week it is
  "Jul 7", with the year only when it is not this one -- the topic-chosen feed
  can be months old, and "437d ago" is arithmetic, not an answer.
- The feed's snippet repeats the headline and a link, so it is not shown.

## How it works

### The topic follows the conversation

What someone has been asking about is a better signal of what they want to read
than a standing profile fact, because it moves with them. So the query is
derived from their recent questions first, with memory used only to
disambiguate or add a location.

| signal available | result |
|---|---|
| Fewer than two signals | General front page. No model call |
| Recent questions | `get_search_feed` with the derived query |
| Questions and memories | Same, with memory as secondary context |
| Model answers `NONE` | General front page |

A new account sees general news rather than a guess from one message, and
generic chit-chat, coding help or creative writing produce `NONE` rather than a
confidently irrelevant strip.

The derived query is cached per user on the same clock as the headlines, so the
new-chat screen does not cost a model call every time it loads. The topic moves
as the conversation does, but not on every page view.

The topic is shown as a badge next to "In the news". Personalisation that cannot
explain itself looks like a random selection.

### Freshest first

The search feed ranks by relevance, which puts month-old articles under a
heading that says "In the news". Items are over-fetched, sorted by publication
date and then trimmed. Undated items sort last rather than being dropped — a
headline with no timestamp is still a headline.

### A real MCP client

`app/tools/news_mcp.py` uses the official Python SDK — `stdio_client` and
`ClientSession` — to spawn an MCP server, initialise a session, and call a tool.
Any server exposing a headlines tool works; `MCP_NEWS_COMMAND` points at it.

The default is [`moltrus/google-news-mcp`](https://github.com/moltrus/google-news-mcp),
pinned at commit `a454db6295776f936146472d660c595f9b9449a1`. Pinned rather than
tracking a branch, so an upstream push cannot break everyone who clones this.

### Two mcp versions, on purpose

That server imports `mcp.server.fastmcp.FastMCP`, which exists only in `mcp<2`.
The backend client runs `mcp` 2.x, where it was renamed to `MCPServer`.

Rather than hold the whole backend on a deprecated major version, the server is
installed into its own virtualenv at `/opt/mcp-news` with `mcp<2` pinned, and
spawned by absolute path. A 2.x client and a 1.x server negotiate protocol
versions and interoperate over stdio — verified before this was designed in, not
assumed.

The upstream `main()` also raises at teardown (it awaits a synchronous `run()`).
That happens after serving completes and is absorbed by the failure path below.

### Failure is always invisible

Every path through `NewsService.headlines()` returns a list. Spawn failure,
protocol error, timeout, malformed payload, unexpected exception — all log and
return empty. The component renders `null` on an empty list: no error state, no
placeholder, no skeleton.

News is a decoration. A decoration that announces its own failure is worse than
one that quietly steps aside.

When a fetch fails but a stale cache entry exists, the stale entry is served.
Yesterday's headlines beat an empty strip.

### Caching

Keyed by `tool:language:country`, stored in Postgres with an `expires_at`. In
Postgres rather than memory so the strip survives a restart and a cold container
does not hammer the MCP server on every boot.

Measured: 24ms cached against several seconds for a cold MCP spawn.

### Parsing is deliberately tolerant

Written against what `google-news-mcp` returns — a JSON object with an `entries`
list — but it accepts `items`, `articles`, `results` or a bare array, and reads
links from `link` or `url`. The point of `MCP_NEWS_COMMAND` is that someone can
point this elsewhere, so assuming one shape would make that setting a lie.

Publisher names come from an explicit `source` field where present, and
otherwise from the `" - Publisher"` suffix Google News puts on every title. The
card shows the publisher separately and strips the suffix from the headline.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MCP_NEWS_COMMAND` | `/opt/mcp-news/bin/google-news-mcp` | Executable to spawn |
| `MCP_NEWS_ARGS` | *(empty)* | Extra arguments, space separated |
| `MCP_NEWS_TOOL` | `get_top_headlines` | Tool called when there is no topic |
| `MCP_NEWS_LANGUAGE` | `en` | Passed to the tool |
| `MCP_NEWS_COUNTRY` | `US` | Passed to the tool. `MY` for Malaysia |
| `MCP_NEWS_TTL_SECONDS` | `1800` | Cache lifetime |
| `MCP_NEWS_TIMEOUT_SECONDS` | `20` | Give-up time for the whole exchange |
| `MCP_NEWS_MAX_ITEMS` | `6` | Cards rendered |

The search tool (`get_search_feed`) is used automatically whenever a topic was
derived; only the headline tool is configurable, since that is the fallback.

## How to extend it

- **A different MCP server**: set `MCP_NEWS_COMMAND`, `MCP_NEWS_TOOL` and
  `MCP_NEWS_ARGS`. If its payload shape is unusual, extend `_entries_from`.
- **An HTTP MCP server**: swap `stdio_client` for the SDK's HTTP client in
  `fetch_headlines`. Nothing else changes.
- **News as chat context**: `NewsItem` maps onto `ToolResult`, so a contributor
  at order 300 could put headlines in the prompt.

## Known limits

- **A subprocess per cache miss.** Spawning a Python interpreter every 30
  minutes is fine; a much shorter TTL would not be.
- **The cache is shared by topic, not by user.** Two people whose questions
  produce the same query share an entry, which is the intent — but it means the
  strip is only as private as the query, and the query is derived from what you
  asked.
- **One model call per topic refresh**, at most once per TTL per user.
- **Topic quality follows the model.** A weak one produces a vague query and a
  vague strip; `NONE` is the safety valve and general news the floor.
- **No pagination or categories.** One tool call, one list.
- **`MCP_NEWS_ARGS` splits on whitespace**, so arguments containing spaces are
  not supported.
- **Upstream is a small third-party repo.** It is pinned, and the failure path is
  the whole mitigation. Vendoring it is a reasonable hardening step.

## Tests

`backend/tests/test_tools.py` — entries becoming items, publisher from the title
suffix, an explicit source winning, the fallback when neither exists, HTML
stripped from summaries, `max_items`, three alternative payload shapes, non-JSON
reported as unavailable, and no usable entries reported as unavailable.

`backend/tests/test_news_topics.py` — 22 tests: plain queries accepted, prose
and markup rejected, a new account getting the front page with no model call, a
single signal being insufficient, recent questions alone being enough, the model
declining with `NONE`, questions labelled as the stronger signal in the prompt,
bounded question count and length, blank questions not counting, and a failing
model falling back.

## Verified

Live against Google News. A new account with no history received the general
front page (`topic: ""`). After two questions about espresso, the same account
received `topic: "espresso coffee beans roasting"` and coffee-roasting
headlines. A second request was served from cache in 24ms.
