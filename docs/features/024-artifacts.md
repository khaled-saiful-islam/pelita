# 024 — Artifacts: posters, slide decks, games, websites and apps

## What it does

Ask for a poster, a deck, a game, a website or an app and get one — designed,
not templated — built while you watch and opened in a panel beside the
conversation.

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

![A poster for a night market in Kota Bharu, designed from a one-line brief](../images/pelita-poster.png)

![A five-slide deck, each slide on one of the grounds its design chose](../images/pelita-slides.png)

![A game, run in a browser before it was shown](../images/pelita-game.png)

![A landing page in the panel, with the Desktop, Tablet and Phone switcher](../images/pelita-website.png)

![An app that remembers what was put in it: a standup spinner](../images/pelita-app.png)

![The build in progress: the artifact forming in its own ground and face, lit in its kind's colour](../images/pelita-building.png)

An artifact is **one self-contained HTML document**. That is the whole format,
and it is why this feature adds no service, no build step and no dependency. A
poster is one canvas; a deck is one `<section>` per slide in the same file; a
website is one `<section data-page>` per page; a game and an app are one
program with their style and script inline.

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

### What the panel shows while it works

Three things, in the artifact's own colours: the steps with their timings,
the artifact forming, and — for a deck — the slides themselves as they land.

The forming card is the thing before it exists. Its proportions are the ones
it chose, its ground is the first colour of its palette, its title is set in
the display face it named (fetched from Google Fonts the moment it is
named), and under that is the one sentence explaining why it looks like this
— for a game, the loop: what the player will actually be doing.

Nothing there is invented. Every value is one the artifact has already
committed to, which is the point: what is on screen while you wait is the
first true thing about what you are going to get.

It has three states, because the build does. Behind it is a glow in the
kind's own colour -- rose for a poster, emerald for a website -- which does not
change when the design lands. Taken from the palette instead, a design with a
gold in it glowed in Pelita's own amber, and every artifact looked like the app.

| | What is on the card | What it looks like |
|---|---|---|
| **reading** | Nothing is decided yet | Dark and unmarked, the kind's usual proportions, two rules holding the space the sentence will take. A low, cool light behind it. |
| **designed** | The look arrived, all at once | Ground, ink and both faces cross-fade in over 700ms, and the card reshapes if this artifact chose a size of its own. The light comes up with the colour. |
| **making** | The document is being written | The same look, more of everything: brighter light, faster. |

Two light bands cross the card half a cycle apart, so one is always on it —
a single band spends a third of its travel off the edge, and a card that
goes still for a second reads as a card that has stopped. Behind it all, a
warm shadow that breathes: the light the thing is being made under, and the
one colour on screen that is not the artifact's own. None of it is a
progress bar. Nothing here claims to know how far along anything is, because
nothing here does.

It replaced a row of colour swatches, which told you a palette had been
chosen and nothing whatever about what was being made — and was shown for
every kind, including a game, where five colours say less than the sentence
above them.

### A build outlives the connection watching it

A build takes minutes, and for all of them the half-written answer exists
only in the client: an artifact is stored once it is finished, and not
before. So anything that broke the connection threw the work away — a
reload, a browser suspending a socket held open on a backgrounded tab, a
proxy's idle timeout, a flaky network. Coming back found the question with
no answer under it.

The turn no longer runs inside the request that asked for it. It runs in its
own task, writes what it emits into a buffer, and connections *subscribe*
(`app/services/live_turns.py`). A subscriber going away cancels the
subscriber. Three things follow:

- `POST /chat/stream` starts the turn and subscribes to it.
- `GET /chat/live/{conversation_id}` picks up a turn already running,
  replayed **from its first event** — so what comes back is the whole build,
  not whatever is left of it. The client asks on the way into any
  conversation, and 204 — nothing running — is the ordinary answer. (It was
404 once, and every browser logs a 404 as a console error on every visit.)
- A dropped connection is retried three times with a backoff, as a *follow*
  rather than a new turn. Only a refusal — the allowance ran out, the
  session expired — stops it trying, because asking again would only be
  refused again.

A finished turn is deliberately not offered: its answer is in the database
by then, and replaying it would draw a second copy of what is already on
screen and count the cost twice.

The client keeps the in-flight answer per conversation as well, so switching
away and back is instant rather than a re-fetch. That buffer is a
convenience; the server is the source of truth.

One further thing had to be true for any of it to work: `load()` must be
referentially stable. The page reloads the conversation in an effect keyed
on it, and that effect calls `reset()` when the route names no conversation
— which aborts the stream. A `load()` that changed identity on every render
therefore killed the turn it had just started. `useChat.test.tsx` asserts
the identity, because nothing about the transcript makes it visible.

### Where the kinds are offered

A Create menu in the composer held them for two kinds. At five it was five
words behind a button nobody opened, so the kinds moved to where the decision is
made: right above the box. The news that used to sit there moved to the top of
the screen.

On a new chat, **Make something** is a row of five tiles, each in its kind's
colour with a few pixels of what it makes, moving -- a poster's sun rising
behind its headline, a deck dealing its next slide, a website scrolling, an
app's buttons being pressed, a snake going round its board -- and one real
example of something to ask for. A light moves from tile to tile every few
seconds: the lit tile plays its scene and turns to its next example, so the row
is never still and never busy. Pointing at a tile takes the light.

Choosing one writes its example into the box **with the subject selected**:
"Design a poster for *a night market in Ipoh, every Friday 6pm*". The next thing
typed replaces the subject and keeps the request; Enter sends the example as it
stands. In a conversation the same five are a slim row of chips that collapses
while something is typed or answered.

Scenes are plain elements drawn in `currentColor`, lit through one `--tile`
custom property, and paused at a first frame drawn to be worth looking at when
not lit. Reduced motion stops all of it.

### Each kind has a colour

A poster is rose, a deck is blue, a game is violet, each with its own mark —
a picture, a presentation, a gamepad. The card in the transcript is washed
and bordered in its colour, the tile behind its glyph is that colour solid,
and the panel header matches. Three artifacts in one conversation are told
apart before they are read.

The colours are tokens in `theme.css` with dark values, deliberately off the
accent ramp: they are categories, not emphasis, and three tints of the brand
would read as three states of one thing. The classes are written out rather
than built from the kind's name, because Tailwind reads them out of the
source — `bg-kind-${kind}` compiles to nothing. A kind with no entry gets the
brand colour and a neutral mark.

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

### Websites, and the one kind that is several things at once

A website is a design system, a header and footer that frame every page, and
the pages. It is built in that order, the way a studio would, and it stays one
file: a download, a share link and a new tab all already understand one file.
"Several pages" is several `<section data-page="...">` elements in one
document.

| step | produces |
|---|---|
| **plan** | what it is for, who it is for, a named direction, and every page with its sections in order |
| **shell** | one stylesheet every page is built from, the header, the footer, a little behaviour — written while the photographs are found |
| **pages** | each written on its own against that stylesheet, three at a time, shown in the panel as they land |
| **opened** | at 1280px and at a 390px phone, every page visited; what is wrong goes back to the part it belongs to |

**How many pages is the plan's call** unless the person says. A landing page, a
launch or an event is one long page with in-page navigation; a restaurant, a
clinic or a studio is Home plus two to four others. A fixed default would be
wrong for one of those every time.

**Writing the pages separately is what makes a five-page site possible.** One
call for the whole site runs out of room around the third page and trails off.
A page written against a finished stylesheet has one job and the whole budget
for it, and the stylesheet — with a comment at the top naming every class and
what it is for — is what keeps five separately written pages looking like one
site.

**Routing is code, not model output.** `site_assembly.py` adds it afterwards:
the page links where the shell left `<!--NAV-->`, a line at the very top of
`<head>` that hides every page but the one the address names before anything is
painted, and one script at the end of `<body>` for routing, scroll-reveal and
forms. It is the same on every site, it is the part that breaks when it is
improvised, and when it breaks the site is not slightly worse, it is one long
page. Three details were not obvious:

- A frame's address can refuse to change, so the page is shown first and the
  address follows. Links are handled by the router rather than left to the
  browser, which also stops a link to another site replacing the website with
  somebody else's page inside the panel.
- A sandbox without `allow-forms` refuses a submission *before* the submit
  event fires, so no script ever hears about it and a contact form is a button
  that does nothing. `SandboxPolicy(forms=True)` lets the event fire;
  `form-action 'none'` still means nothing is ever sent anywhere. The router
  checks the form and shows its `.form-success` in its place.
- A page may carry no script and no inline handler — both are stripped — and
  every word a visitor reads is in the HTML, never written by script. That is
  what lets the pencil edit a website: the words on screen are the words the
  server numbers.

Two guards sit in that stylesheet, both at zero specificity with `:where()`,
so any rule the design wrote still wins:

- `min-width: 0` on everything inside a page. Grid and flex items refuse to
  shrink below their content unless told they may, and a one-column grid whose
  track grew to its content's width was 24px past a 390px phone on the first
  real site built — the whole page scrolled sideways. A test reproduces it and
  proves it fails without the guard.
- Photographs are set directly on the element. The shell and a page are
  separate calls and each invents its own way of passing a picture along: on
  that same first site the shell's `.media` showed `var(--img)` only with a
  `data-img` attribute, the page set `--img: var(--photo-2)` without one, and
  the hero was an empty brown box. Any element whose style names a photograph
  now also gets it as its `background-image`, whatever either thought the
  convention was.

Everything added is marked `data-pelita`, so it is taken out and put back
exactly when the site changes; a site read back and reassembled is the same
bytes.

**Opened, not read.** A site fails in ways the markup does not announce: a
script that throws so the menu never opens, a page with nothing on it, a
pricing table 1100px wide that on a phone scrolls the whole site sideways.
`sitetest.py` opens the site in the export browser at both widths and visits
every page. At phone width it names the outermost element that runs past the
edge — not a strip scrolling inside its own box, not a drawer tucked
off-canvas — and which page it is on. Errors go to the shell, because pages
have no scripts; a wide table goes to its page. One round of repairs, each part
fixed on its own and all at once, then it is opened again.

**Changing one** is sent to the part it belongs to. A word or a colour is a
find-and-replace; a new page is written against the existing stylesheet and
added to the nav; a page that needs a different structure is rewritten alone.
Everything else is untouched by construction.

In the panel a website fills the height and scrolls, laid out at the width of
the screen being looked at — **Desktop**, **Tablet** or **Phone** — rather than
at whatever width the panel happens to be, which is nobody's device. Its pages
are repeated as tabs above it, synced by message with the router inside the
frame. It downloads as one HTML file with every page in it.

### Apps, and the one kind that remembers

An app is a tool somebody uses: a calculator, a wheel of names, a task board,
a budget, a timer. It is built the way a game is, because it is the same shape
of thing -- one program, designed first, written in one call, proved by being
used -- and shown the way a website is: filling the panel, with Desktop, Tablet
and Phone.

| step | produces |
|---|---|
| **design** | the job, the three to five core actions, what it keeps, the first screen, the one detail that shows care, the look |
| **write** | the whole self-contained document, in one call, at most about 50 KB; one cut off before `</html>` is written again, tighter |
| **use it** | typed into, Enter pressed, every button pressed at 1280px; measured at a 390px phone; what broke goes back, twice at most |

**Loading an app proves very little.** A task board renders perfectly and
throws the moment somebody presses "Add"; the failures live behind the
controls. `apptest.py` fills every text field with something plausible for its
type, presses Enter, presses up to twelve buttons in turn, and reads the
console. A `confirm()` or `alert()` is recorded as a failure too: those are
blocked in the frame, so a question asked with one is never asked.

**What it keeps is saved on the account.** The frame has an opaque origin, so
`localStorage` throws and the app cannot call the API. It is given
`PelitaStore` instead (`app_runtime.py`), in front of its own script:

    const state = PelitaStore.load({ tasks: [] })   // saved data over these defaults
    PelitaStore.save(state)                          // batched; call it as often as you like

In the panel, what was saved is fetched from `GET /artifacts/{id}/state` and put
into the document before it is framed, so `load` is synchronous and the first
paint already has your tasks. Every `save` goes to the panel by message, and the
panel `PUT`s it, batched, for this person and this artifact only -- 256 KB at
most, owner-only, one row overwritten rather than a history. **Start over**
clears it. A new version of the app, after a change in the chat, opens with what
was typed a minute ago, not what was loaded at the start; `load` merges over the
defaults, so a field the new version adds still has a value.

A **share-link visitor** has no account, and the owner's data is not theirs to
see -- a shared task board that showed somebody else's tasks would be a leak.
So a shared app is handed out empty and the visitor's copy is kept in their own
browser. A **downloaded** copy uses that browser's storage, keyed by an id the
app keeps across every change. Opened in a new tab, it runs and forgets.

In the panel an app is laid out at the panel's own width at full size, where a
website is shrunk to show its desktop layout: a site is looked at, an app is
used, and at half size its buttons are too small to press.

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
registry, and so is the Make rail above the composer — a new kind is offered to
the model and shown to the person by existing, in the brand colour with a
spinning mark and its own description as its example until somebody gives it a
colour, a scene and examples of its own (`kind-look.ts`, `Scene.tsx`,
`showcase.ts`).

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
  finished one. While it builds, the panel shows the steps and the artifact
  forming: its real proportions, its real ground, its title set in the face
  it has just chosen and the sentence justifying it. Never the markup being
  written, which is not a preview of anything, and never a row of colour
  swatches, which says a palette was chosen and nothing about what is being
  made. A deck replaces it with real slides as they land.
- **The fit measurement lands a few seconds after the poster does.** It waits
  for fonts, so a poster that does not fit is shown before it is flagged.
- **The design prompt is English-only**, in line with the other pattern layers.
  The poster's own words follow the conversation's language.
- **No queue.** A second concurrent build on one worker competes for the same
  event loop.
- **Running turns live in the process.** `LiveTurns`, like
  `CancellationRegistry`, is in-memory: one worker. A restart ends every
  build in flight, and to run several workers it needs a shared store and a
  pub/sub channel. The interface is three methods and nothing outside the
  file knows how it works.
- **A website's photographs are backgrounds.** They arrive as CSS variables, so
  they cannot be an `<img>`; a site uses them on `.media` blocks and heroes.
- **Up to six photographs per site**, each a few hundred kilobytes embedded. A
  site with every one of them is a two-megabyte file.
- **Pages are written in parallel, and a failed one is dropped** with its nav
  link rather than shipped empty. The home page failing fails the build.
- **A website build is two to three minutes.** The shell's stylesheet is the
  largest single thing any kind writes and nothing else can start until it
  exists, so the shell is held to about 14 KB: the first real site, before
  that, spent 200 of its 284 seconds on a 39 KB stylesheet; the next, with it,
  was built end to end in 134. A one-page site is one long page written in one
  call, and cannot be split across writers the way pages are.
- **A model's own conventions can still disagree.** The shell and each page
  are written separately; the guards above cover the two disagreements found
  so far (photographs, and grid items that will not shrink). Others will
  exist.
- **An app is checked by a robot that does not know what it is for.** It
  presses every button once; it does not notice that "Add" adds the wrong
  thing, or that a total is off by one.
- **An app has no network.** One that would need live data -- rates, weather
  -- is built on realistic sample data and says so.
- **An app opened in a new tab forgets.** It runs under the same opaque origin
  and nothing can save for it there. The panel, the share link and a download
  all remember.
- **The build clock restarts when the page does.** The steps replay with the
  server's own timings in them ("Composing 13.8 KB in 70s"), but the elapsed
  counter in the header counts from when this browser started watching.
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
