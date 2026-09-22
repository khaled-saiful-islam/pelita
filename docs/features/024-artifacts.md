# 024 — Artifacts, starting with posters

## What it does

Ask for a poster and get one — designed, not templated — built while you watch
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

An artifact is **one self-contained HTML document**. That is the whole format,
and it is why this feature adds no service, no build step and no dependency.

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
| slides *(later)* | minimal | fonts only | `allow-scripts` |
| app *(later)* | yes | allow-list | `allow-scripts` |

A poster is static art, so the frame it renders in cannot run a script. The
same policy drives the iframe attribute and the `Content-Security-Policy`
header, so the preview, a new tab and a shared link cannot drift into
disagreeing.

### Editing, in three tiers

| change | how | cost |
|---|---|---|
| a word is wrong | the pencil: edit it on the poster | no model call, instant, no new version |
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
ARTIFACT_MAX_BYTES=262144
ARTIFACT_MAX_PER_CONVERSATION=10
```

Empty `ARTIFACT_MODEL` means no kinds, which means the tool is never offered —
the same rule as search without a key.

## How to extend it

**A new kind** — slides, a one-page app, a résumé — is one file implementing
`ArtifactKind` and one line in `artifacts/registry.py`. It brings its own
schema fragment, prompt, canvas and sandbox policy. The tool's `kind` enum is
built from the registry, so a new kind is offered to the model by existing.

**A build queue.** Generation runs inside the open SSE stream, which is right
for a single-worker deployment. `ArtifactKind.build` is an interface; a queued
implementation swaps in without touching the tool, the events or the panel.

**Patch-based editing.** Add it behind the same entry point once full rewrite
is dull. A non-matching patch must raise loudly — a silent no-op is the
documented failure of every implementation that has tried it.

## Known limits

- **The model cannot make images.** Posters are typography, CSS gradients and
  inline SVG. A real constraint on what a poster can be, not a phase.
- **One artifact per turn.** Two would race for the same panel.
- **A build is 40–90 seconds**, roughly half of it refinement.
- **A content edit costs a composing call.** Only words are free.
- **Print fidelity is the browser's.** No bleed, no crop marks, no CMYK. A
  document that prints well, not a press-ready file.
- **The preview is not progressive.** The first look at the poster is the
  finished one; only the source streams.
- **The fit measurement lands a few seconds after the poster does.** It waits
  for fonts, so a poster that does not fit is shown before it is flagged.
- **The design prompt is English-only**, in line with the other pattern layers.
  The poster's own words follow the conversation's language.
- **No queue.** A second concurrent build on one worker competes for the same
  event loop.
- **The fit check runs in the browser, not at build time.** A poster that fails
  it is shown with a warning rather than automatically redrawn.

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
