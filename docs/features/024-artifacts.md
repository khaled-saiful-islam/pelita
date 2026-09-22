# 024 — Artifacts: posters, slide decks and games

## What it does

Ask for a poster, a deck or a game and get one — designed, not templated — built while you watch
and opened in a panel beside the conversation.

```
you   Design a wide banner for a badminton tournament at Dewan
      Serbaguna Cheras, 14 March, doubles only, RM20 per pair.

      ┌─ Designing ────────────────────────────────────┐
      │ ✓ Read the brief · Badminton Tournament Banner  │
      │ ✓ Chose a direction · Court Geometry            │
      │   #0E2A22 · #E8E3D3 · #D8402F                   │
      │ ✓ Composing                                     │
      │ ✓ Checking it fits                              │
      │ ◐ Refining                                      │
      └─────────────────────────────────────────────────┘
```

![A poster designed from a one-line brief](../images/pelita-poster.png)

![A deck, each slide on one of the grounds its design chose](../images/pelita-slides.png)

![A game, played to a game over, from a one-line brief](../images/pelita-game.png)

![The build in progress: steps, timings and the palette it chose](../images/pelita-building.png)

An artifact is **one self-contained HTML document**. That is the whole format,
and it is why this feature adds no service, no build step and no dependency. A
poster is one canvas; a deck is one `<section>` per slide in the same file.

## How it works

### The chat model writes a brief, never the poster

`create_artifact` takes `{kind, title, brief, style_hints, data}` and has no
parameter for code. A separate model with a much larger output budget does the
designing.

The split is what lets the composing step carry a prompt full of design
instruction and a 16k output budget without any of that weight riding along in
the chat turn's context on every message afterwards.

### Four steps, not one

| step | produces | shown as |
|---|---|---|
| brief | the tool call | Read the brief |
| **direct** | a `DesignSpec`: movement, palette, two faces, canvas | Chose a direction |
| **compose** | the document, streamed | Composing |
| **validate** | findings, and one repair if needed | Checking it fits |
| **refine** | a revision that may only remove | Refining |

The first step invents a named aesthetic — "Midnight Brass", "Ketupat
Sunlight" — deliberately in the abstract, without naming the subject. That is
what stops every poster converging on the same look. The last is forbidden from
adding anything; on its first real run it deleted a duplicated flex block and
some dead CSS and touched nothing else.

Nothing about the result is fixed. The model chooses its own palette, its own
two faces from anything Google Fonts serves, and its own canvas — a printed
flyer, a square social post and a wide banner are the same kind and different
shapes. Only a floor, a ceiling and a default are imposed on the size.

### Slide decks

A deck is the second kind, and the seam held: one file implementing
`ArtifactKind`, one line in the registry. It is built in three jobs, because
they are three jobs and a model asked to do all of them at once does the last
one badly.

| step | produces |
|---|---|
| research | what the web says about the subject, when a search key exists |
| **outline** | what the talk argues, and what each slide does for it |
| **design** | one stylesheet the whole deck shares: palette, two faces, a layout per slide type |
| **write** | one call per slide, three at a time |

#### The grounds a deck moves between

A deck where every slide is the same colour reads as one long slide. So the
design names two to four **grounds** — classes of its own invention, after
the subject — and the pipeline puts one on each slide.

The names are the design's, not the code's. A deck about highland coffee
chose `canopy`, `mist`, `terracotta` and `harvest`; one about Brutalism in KL
chose `concrete`, `ochre`, `terracotta` and `ink`. Nothing in the repository
contains either list.

What the code decides is only the rhythm: the slides meant to land — title,
closing, statement, quote — take the emphatic ground, the rest share the
others, and a run of three identical slides is broken up, because a title,
three `points` and a closing would otherwise be three of one colour in the
middle.

The class is applied after the slide is written rather than asked for in the
prompt. A deck whose grounds alternate only when the writer remembered is a
deck of one ground — and a writer handed the stylesheet will pick a ground of
its own, so the ones it was not given are stripped. A ground the stylesheet
names but never defines does not count; the design is asked again.

The outline is where a deck is won or lost, so that prompt is the longest one
in the feature. Each slide names its layout from a fixed set — title, agenda,
statement, points, split, compare, data, quote, process, image, closing — and
the same layout may not run three times, because a deck of ten bullet slides is
the most boring object in professional life. Text is bounded at 12–55 words a
slide: fewer is a poster, more is a document somebody reads while you talk over
it.

Slides are written at once and **reported in order**. Out of sequence they
arrive as a jumble. The plan is announced before any slide exists, so the panel
puts up the whole shape and fills it in.

Five slides — the default when nobody says a number — take about ninety
seconds, of which the first seventy are deciding what to say and how it should
look. That fixed cost is why the default is five and not ten: the second five
slides roughly double the wait.

**Navigating**: previous and next, a counter with the current heading, arrow
keys, Home and End, and a filmstrip of real thumbnails. The deck is loaded once
and translated by whole slides rather than reloaded — reloading flashes and
refetches the fonts, and hiding the other slides with `display: none` stops CSS
counters, which numbers every slide one.

**Changing a deck** has three shapes: edit what is on the slides, add a slide,
remove one. Adding writes the new slide against the deck's own stylesheet, so
it belongs. All three make a new version; correcting a word with the pencil
still does not.

**Downloading** a deck gives a PDF, one slide to a page.

### Games, and the one kind that executes

A game is the first artifact here that runs code, and the architecture already
had the place for it: `SandboxPolicy` is declared per kind, so `scripts=True`
is the whole of the privilege change. The frame gets `allow-scripts` and
**not** `allow-same-origin`, which is an opaque origin -- the game cannot read
a cookie, reach the page that framed it, or call this API with credentials.
The same policy becomes the CSP when the file is served on its own, and
`connect-src 'none'` means it cannot phone home from either.

It is built in three steps, and the third is the one that matters.

| step | produces |
|---|---|
| **design** | the loop, the pressure, the levels *with their numbers*, palette, faces |
| **write** | the whole self-contained document, in one call |
| **playtest** | it is run in a real browser, and what broke goes back to be fixed |

The design step exists because "snake" is not a brief. What makes a game worth
five minutes is the one decision the player makes over and over and how it gets
harder, so that is decided and named first -- and levels are specified in
numbers (`speed_ms: 140`), because "faster" is not a level.

**The playtest is the part that is not done elsewhere.** A poster is wrong in
ways you can see by reading it. A game is wrong in ways that only appear once
the loop starts: a function called on the first frame and defined nowhere is
invisible to any parser. So the browser already present for PNG and PDF export
opens the game, lets it run, presses the arrow keys and space, clicks, and
reports. Four things come back: what the console said, whether anything was
painted, whether the game is still asking for frames, and whether it tried to
reach the network. Up to two fixes are attempted before it is shown with the
problem named.

Counting the loop is subtler than it looks. A browser ticks whether or not
anything is listening, so "did `requestAnimationFrame` fire" says nothing --
the question is whether the *game* asked for another frame. A counter is
prepended to the document, wrapping `requestAnimationFrame` and `setInterval`,
and counts the game's own calls. Injecting it with `add_init_script` instead
does not work: that runs at document-start of a navigation and `set_content`
rewrites the document, so the counter came back `undefined` and every game
looked stopped.

What a static read still catches first, because it is cheaper than a browser:
a `while (true)` that would hang the tab rather than throw, a `fetch`, a
`<script src>`, no loop at all, and nothing reading input. Only the contents of
`<script>` are searched, so a game *about* networking may say `fetch` in its
own text.

A game downloads as HTML and nothing else. A picture of a game is its first
frame with nobody playing.

### A photograph, when the design wants one

A model cannot produce a photograph, and one asked for a picture writes a URL
that looks plausible and resolves to nothing. So the rule is not "no images" —
it is that a poster may only use a picture it was **given**.

The direction step may ask for one, with search terms rather than a URL. It is
searched for, downloaded, downscaled to what the canvas can use, and embedded
as a data URI. The composing model is told a CSS variable holds it and never
sees the bytes: a base64 photograph in a prompt costs more than the whole
poster, so it goes in after the model has finished, and comes back out again
before any later pass sends the document back.

Embedding rather than linking keeps three promises the rest of the feature
already makes — the document stays one file that prints and downloads, a shared
poster does not report its readers to a stranger's host, and the picture cannot
vanish from under it later.

The direction step is told that most good posters are type, colour and drawn
shape, and that a stock photograph behind a headline is the most generic thing
a poster can be. If the person asked for an image, they get one: their words
win. Asking for one in the chat works too — a change that mentions a picture
triggers the same search.

Without a search key there is nothing to find, and posters are designed without
photographs.

### Nothing may be cut off

The one defect a person sees instantly. Three defences, because no one of them
is enough:

1. **The canvas clips.** `overflow: hidden` means the poster is exactly its
   frame in the panel, in its own tab, in a shared page and on paper.
2. **The prompt specifies the frame** rather than describing it — margins
   zeroed, exact pixel canvas, a flex column. Window units (`vh`, `vw`) are
   banned outright: they measure the browser window, and this document has four
   windows and one correct size. So are `position: fixed`, inner scrolling,
   `nowrap` on anything holding words, and fixed heights that must add up.
3. **`overflow: hidden` anywhere but the canvas is a validation failure.** A
   headline block set to clip itself cuts the tail off its own `g`, which reads
   as a broken font rather than a layout mistake and is missed every time.

Then it is measured for real. Static checks cannot prove a layout fits —
whether a headline wraps to three lines depends on the font that loaded. So the
finished document is rendered in a throwaway frame, its fonts are waited for,
and every element with words of its own is checked against the canvas. Nothing
is shown until that answers.

### The sandbox belongs to the kind

| kind | scripts | network | iframe |
|---|---|---|---|
| **poster** | none | fonts only | `sandbox=""` |
| **slides** | none | fonts only | `sandbox=""` |
| app *(later)* | yes | allow-list | `allow-scripts` |

Slides need no scripts either: navigation happens in the panel, which moves the
frame rather than reaching into it.

A poster is static art, so the frame it renders in cannot run a script. The
same policy drives the iframe attribute and the `Content-Security-Policy`
header, so the preview, a new tab and a shared link cannot drift into
disagreeing.

### Editing, in three tiers

| change | how | cost |
|---|---|---|
| a word is wrong | the pencil: edit it on the poster | no model call, instant, no new version |
| add or change a picture | say so in the chat box | a search plus one call |
| the design | say so in the chat box | ~40s, a new version |
| a different idea | ask for a new one | a full build |

Design changes go through the same chat box as everything else. The message
carries whichever artifact the panel is showing, and `edit_artifact` is offered
only on a turn that has one — so "make it warmer" means the poster on screen
rather than a new poster about warmth, and the model is never shown a way to
change nothing.

Fixing a word corrects the current version in place. A version list where every
entry differs by one character is a version list nobody reads.

Editing words needs a script, and a poster renders with scripts disabled. Edit
mode re-renders the frame with `allow-scripts` and one script that **we**
inject, which turns each run of text into a `contenteditable` span. That script
is never model output, the validator guarantees the document carries none of its
own, and the frame still has no `allow-same-origin`.

The document is split into tags and the text between them; runs are numbered in
document order and an edit names a number. Every tag, attribute and byte of CSS
is copied through untouched, which is what makes it safe with nothing checking
the result.

### Saving it

The download is a **picture** by default. A poster goes into a message, a feed
or a noticeboard, and none of those take an HTML file. That needs a real
browser, because nothing else renders a document the way the one the reader is
looking at does — so the backend image carries headless Chromium, opens the
poster, waits for its fonts and screenshots the canvas at twice its size.

The document is the second option, and is what to keep to edit or print it
later. `ARTIFACT_EXPORT_PNG=false` turns the picture off for a deployment that
only wants the file, and the Chromium line can then come out of the Dockerfile.

### Sharing

A frozen copy of one version, on a 256-bit token, with its kind's sandbox
policy, `noindex` and `no-store`, and its own rate-limit bucket. A link that
followed the artifact would republish every later edit without the owner
deciding to. A revoked link answers exactly as one that never existed.

## Configuration

```
ARTIFACTS_ENABLED=true
ARTIFACT_MODEL=                  # empty turns the whole feature off
ARTIFACT_BASE_URL=               # defaults to LLM_BASE_URL
ARTIFACT_API_KEY=                # defaults to LLM_API_KEY
ARTIFACT_MAX_TOKENS=16384
ARTIFACT_TIMEOUT_SECONDS=300
ARTIFACT_REFINE_PASS=true        # roughly doubles the wall clock
ARTIFACT_MAX_BYTES=1500000        # generous: a photograph travels inside the file
ARTIFACT_EXPORT_PNG=true         # needs Chromium in the image
ARTIFACT_PLAYTEST=true           # run a game before showing it; same Chromium
ARTIFACT_MAX_PER_CONVERSATION=10
```

Empty `ARTIFACT_MODEL` means no kinds, which means the tool is never offered —
the same rule as search without a key.

## How to extend it

**A new kind** — a one-page app, a résumé, a certificate — is one file implementing
`ArtifactKind` and one line in `artifacts/registry.py`. It brings its own
prompt, canvas and sandbox policy. The tool's `kind` enum is built from the
registry, and so is the Create menu in the composer — a new kind is offered to
the model and shown to the person by existing.

**A build queue.** Generation runs inside the open SSE stream, which is right
for a single-worker deployment. `ArtifactKind.build` is an interface; a queued
implementation swaps in without touching the tool, the events or the panel.

**Patch-based editing.** Add it behind the same entry point once full rewrite
is dull. A non-matching patch must raise loudly — a silent no-op is the
documented failure of every implementation that has tried it.

## Known limits

- **A game is played by a robot, not a person.** The playtest presses keys and
  looks for crashes. It does not know whether the game is any *good*, whether
  level three is reachable, or whether the collisions are fair.
- **A game is changed by rewriting it.** A find-and-replace inside a program
  does not fail loudly; it stops working somewhere the person has not reached
  yet. The rewrite costs more and is checked by playing the result.
- **The playtest adds a few seconds** to every game build and needs the same
  Chromium the PNG export does. `ARTIFACT_PLAYTEST=false` skips it, and the
  game is shipped unplayed with the person told so.
- **The model cannot make a picture, only find one.** There is no image model
  here, so a photograph is searched for. When nothing suitable is found the
  poster is designed without one.
- **A found photograph is somebody else's.** The source page is recorded on the
  artifact, but nothing checks its licence.
- **One artifact per turn.** Two would race for the same panel.
- **A deck takes about ninety seconds** for the default five slides, and
  costs roughly twice a poster. Ten slides is about two minutes.
- **Speaker notes are in the file but nothing shows them yet.** They are
  `display: none`, waiting for a present mode.
- **A poster build is 40–90 seconds when nothing needs fixing**, but a
  poster that fails its own check is corrected and refined, and observed
  builds have reached 270. Roughly half of any build is refinement.
- **A content edit costs a composing call.** Only words are free.
- **Print fidelity is the browser's.** No bleed, no crop marks, no CMYK. A
  document that prints well, not a press-ready file.
- **A poster's preview is not progressive.** The first look at it is the
  finished one. While it builds, the panel shows the steps, their timings and
  the palette the design settled on — never the markup being written, which
  is not a preview of anything. A deck does show its slides as they land.
- **The fit measurement lands a few seconds after the poster does.** It waits
  for fonts, so a poster that does not fit is shown before it is flagged.
- **The design prompt is English-only**, in line with the other pattern layers.
  The poster's own words follow the conversation's language.
- **No queue.** A second concurrent build on one worker competes for the same
  event loop.
- **The fit check runs in the browser, not at build time.** A poster that fails
  it is shown with a warning rather than automatically redrawn.
- **A deck's slides are not fit-checked at all.** The poster's checks are
  structural and run on its markup; nothing measures a rendered slide. A
  title slide measured 235px of overflow past its own bottom edge, clipped
  silently by `overflow: hidden`, while the other five slides in the same
  deck were clean. Catching this needs a headless pass over the built deck,
  which is not written.

## Tests

- `test_poster.py` — the pipeline against a fake provider, including every
  failure path, and a digest pinning the three prompts so a change to the
  product is a visible diff.
- `test_artifact_validation.py` — one document that fails each check and one
  that passes.
- `test_artifact_text_edit.py` — numbering, escaping, and the `<title>`
  off-by-one that sent an edit to the wrong run.
- `test_artifact_tool.py` — the whole turn: the model asks, a kind builds, the
  turn stores it and the browser is told where it is.
- `test_artifact_routes.py` — reading, versions, sharing, downloading, and what
  a stranger cannot reach.
- `fit-check.test.ts`, `fit-to-panel.test.ts` — the frame's permissions, who may
  answer it, and any poster shape fitting any panel.

## Verified

- Two briefs through the same code produced "Humid Brass" on A4 in Italiana and
  "Ketupat Sunlight" at 1080×1350 in Bricolage Grotesque, having read "not a
  printed flyer" and changed the shape.
- A deliberately overloaded brief — five schedule rows, four detail fields,
  three sponsors — laid out with nothing clipped, measured in a browser.
- A banner brief produced 1920×720, scaled to 0.33 in a 662px panel.
- The fee on that banner edited from 20 to 25 in place; the stored diff between
  v1 and v2 is one line, with the currency span beside it untouched.
