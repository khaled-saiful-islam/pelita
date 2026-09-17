# 012 — News strip

## What it does

Headlines above the composer on the new-chat screen, as clickable cards that
open in a new tab. Pulled from an MCP server, cached in Postgres for 30 minutes.
If anything fails, the strip is hidden and chat is untouched.

## How it works

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
| `MCP_NEWS_TOOL` | `get_top_headlines` | Tool name to call |
| `MCP_NEWS_LANGUAGE` | `en` | Passed to the tool |
| `MCP_NEWS_COUNTRY` | `US` | Passed to the tool. `MY` for Malaysia |
| `MCP_NEWS_TTL_SECONDS` | `1800` | Cache lifetime |
| `MCP_NEWS_TIMEOUT_SECONDS` | `20` | Give-up time for the whole exchange |
| `MCP_NEWS_MAX_ITEMS` | `6` | Cards rendered |

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
- **Cache is global, not per user.** Everyone sees the same headlines for the
  configured language and country.
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

## Verified

Live against Google News: six real Malaysian headlines from Malaysiakini, The
Star and Borneo Post, rendered as cards with publisher badges. Second request
served from cache in 24ms.
