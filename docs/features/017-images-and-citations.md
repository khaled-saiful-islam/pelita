# 017 — Image search and clickable citations

## What it does

Two things that make an answer checkable rather than merely readable.

**Citations** — the `[1]`, `[2]` markers in an answer are links to the source
they cite, with a preview card on hover.

**Images** — asking to be *shown* something searches for pictures and renders
them as a grid above the answer.

## Clickable citations

### The problem

The model is asked to cite inline and does, but as plain text. Reading `[3]`
meant scrolling to a collapsed list and counting — which is the same amount of
work as having no citation at all.

### How it works

`linkCitations()` rewrites the markers into markdown links before rendering, so
nothing about how answers are produced had to change. It is a string transform
rather than a rehype plugin because the rule is genuinely textual, and the hard
part — not touching code — is easier to reason about on raw markdown than on a
tree.

What it deliberately leaves alone:

| input | why |
|---|---|
| `` `items[1]` `` and fenced blocks | Array indexing, not a citation |
| `[1](https://…)` | Already a link; rewriting yields `[1](new)(old)` |
| `![1](https://…)` | An image |
| `[7]` with five sources | A model citing a source that does not exist should look wrong, not link somewhere arbitrary |

A group like `[1, 2]` becomes two adjacent links so each number goes to its own
source.

### The hover card

The native `title` attribute technically works. It waits about a second, renders
as an unstyled OS tooltip, and shows one line. The card shows the host, the
title and the snippet, opens after 120ms and closes after 140ms — instant on
open makes text twitch as the pointer crosses it, instant on close makes the
card impossible to move onto.

It opens on keyboard focus too, so the preview is not mouse-only.

## Image search

### When it runs

Detected by pattern, in `search_intent.py`: *show me a picture/photo/image of*,
*what does X look like*, *diagram of*. These phrasings are few and explicit, and
a model call to recognise "picture of" would be spending money to read English.

The image check runs **before** the negative patterns, because "show me a
picture of a moka pot" contains no creative-task words but "draw me a picture"
would, and the image reading is the more specific one either way.

### What is filtered out

| filter | reason |
|---|---|
| Stock libraries — Shutterstock, Alamy, Getty, iStock, Dreamstime and others | They serve watermarked previews to non-subscribers: a technical match, visually useless |
| Images under 200px on either edge | Icons, avatars and tracking pixels rather than pictures of the subject |
| Results with no usable page URL | A picture with no context is not a source anyone can check |

Ranks are assigned **after** filtering, so the numbering has no gaps where a
stock photo was dropped. An unreported size is never treated as tiny.

### Two things that were wrong at first

**A second search ran needlessly.** The turn did an image search *and* a text
search. That doubled the latency of the slowest part of the turn, and on one
run it pushed the second call into a timeout whose "Search unavailable" chip
then contradicted the images that had just been found. "Show me X" is answered
by the pictures plus what the model already knows, so the text search is skipped.

**The model said it could not show images.** It had no idea a grid was being
rendered above its reply, so it apologised for being unable to do the thing the
user could see it doing. The tool-results contributor now tells it what the
reader can already see, and asks it to add what the pictures do not convey.

### Rendering

Tiles link to the page the image appears on, not to the image file. Thumbnails
load lazily with `referrerPolicy="no-referrer"`, so the chat URL is not sent to
whatever host serves the picture. A tile whose thumbnail fails to load removes
itself rather than leaving a broken-image icon.

## Search timing

The tool chip now reads `5 results in 0.8s` rather than `5 results`. When a turn
feels slow, the question is whether the wait was the search or the model, and a
count alone does not answer it.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `IMAGE_MAX_RESULTS` | `6` | Tiles rendered |
| `SEARCH_MAX_RESULTS` | `5` | Text results, unchanged |

## Known limits

- **Image intent is English-only**, like the rest of the pattern layer.
- **The stock-library list is finite.** A watermarked site not on it gets
  through; it is a blocklist, not a watermark detector.
- **Images are not described to the model.** It is told they exist and what they
  are titled, not what is in them — there is no vision call.
- **Thumbnails are hotlinked.** They can rot, and some hosts block hotlinking;
  the tile disappears when that happens.
- **A grid of entirely dead thumbnails renders as nothing**, while the answer
  still refers to images. Each tile removes itself on error, and none of them
  knows the others also failed.
- **Citation rewriting is textual.** A `[1]` inside an HTML block in markdown is
  not protected the way fenced code is.
- **The hover card has no collision detection.** Near the top of the column it
  can be clipped; it is constrained in width but not repositioned.

## Tests

`frontend/src/lib/citations.test.ts` — image results moved out of sources on
reload, ordinary citations left alone, mixed sets separated, a result with only
a full image treated as an image, and untouched messages returned by identity.

 — 14 tests: single and multiple markers,
grouped markers splitting, unknown ranks left as text, groups with a missing
member, fenced and inline code untouched, existing links and images not
re-wrapped, quote escaping in titles, no sources, and empty input.

`backend/tests/test_tools.py` — image results linking to the page not the file,
data-URI thumbnails never used as links, six stock hosts skipped, a library
named only in the source field skipped, tiny images skipped, unreported sizes
kept, contiguous ranks after filtering, and HTML entities decoded in both search
and news parsing.

### Images survive a reload

Image results and citations live in the same table, because an image result *is*
a source. They render as very different things, so the frontend splits them
apart when a conversation is loaded.

Getting this wrong is invisible while streaming and obvious afterwards: the grid
appeared during the answer and came back as a list of links on refresh, because
the stored rows arrived in `sources` and nothing moved them into `images`. The
API response also has to carry `thumbnail_url` and `image_url`, or there is
nothing to split on.

## Verified

"Show me pictures of the Petronas Towers" returned six photographs from
Wikipedia, RICS, blogs and Instagram with no stock results, and the answer
opened "The images show the Petronas Towers…". A search answer rendered
citations as chips whose hover cards showed `asia.nikkei.com`, the page title
and its snippet, each linking to the real URL.
