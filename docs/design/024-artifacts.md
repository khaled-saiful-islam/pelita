# 024 — Artifacts (design)

**Status:** superseded by [`docs/features/024-artifacts.md`](../features/024-artifacts.md).
Built, and grown since: slide decks, games, websites and apps followed the
poster. This is the design as it was first written, kept for its reasoning;
where the two disagree, the feature document is right.

## What it does

Ask for a poster and get one — designed, not templated — built while you watch
and opened in a panel beside the conversation.

```
you   Make me a poster for a Friday night jazz set at Bar Kopi,
      9pm, RM35 at the door.

      ┌─ Designing a poster ───────────────────────────┐
      │ ✓ Read the brief                                │
      │ ✓ Chose a direction · "Midnight Brass"          │
      │   ink #12151C · brass #C8963E · bone #EDE6D8    │
      │ ◐ Composing…                                    │
      │   Checking it fits                              │
      └─────────────────────────────────────────────────┘

      Here it is — brass on near-black, the set time carrying
      the hierarchy. Tell me what to change.

                        ┌──────────────────────────────────────┐
                        │ Midnight Brass      ▾v2  ⋯  ⇱  ×    │
                        ├──────────────────────────────────────┤
                        │                                      │
                        │          [ the poster ]              │
                        │                                      │
                        ├──────────────────────────────────────┤
                        │ Preview │ Source     Share  ⇱  ⤓  ⎙ │
                        └──────────────────────────────────────┘
```

A poster is one self-contained HTML document. That is the whole format, and it
is why this feature adds no service, no build step and no new dependency.

## Why this shape

Six decisions carry the design. Each is written down with the alternative it
beat, because the alternatives are all defensible and someone will propose them
again.

### 1. The artifact is an HTML document

A poster is one HTML document with its CSS inline and its graphics in CSS and
SVG. Not a React component, not a template plus data.

The reference implementation in ILMUchat generates JSX, and that single choice
is what forces four services on it: a Node transpiler to run the JSX, a fixed
import allow-list, a validator sidecar and a separate renderer origin. None of
that is about posters. It is the cost of shipping a component instead of a
document.

A document, by contrast:

| | |
|---|---|
| renders | the browser already knows how |
| opens in a tab | serve it |
| exports to PDF | the browser prints it; `@page` controls the sheet |
| downloads | it is already a file |
| validates | `html.parser`, in the standard library, inside `pytest` |
| costs | no new service, no new dependency, no new language in the repo |

It also generalises further than JSX does. A slide deck is `<section>` elements
in one document. A small interactive app is the same document with a `<script>`
in it. One currency, one panel, one share route, one export path — the kinds
differ in what they are *allowed* to contain, not in how they are carried.

### 2. `kind` is a plugin, and so is its sandbox

Rule 2 of `CLAUDE.md` — everything pluggable is a Protocol plus a registry —
applies here without amendment.

```python
class ArtifactKind(Protocol):
    name: str                       # "poster"
    schema: dict[str, Any]          # merged into the tool's parameters
    canvas: Canvas                  # 794×1123 at 96dpi, for a poster
    sandbox: SandboxPolicy          # what the document may do
    async def direct(self, brief: Brief) -> DesignSpec: ...
    async def compose(self, spec: DesignSpec) -> AsyncIterator[str]: ...
    def validators(self) -> tuple[Validator, ...]: ...
```

Adding slides later is `artifacts/slides.py` plus one line in
`artifacts/registry.py`. Nothing in the tool, the service, the panel, the share
route or the export path learns a second name.

The part worth dwelling on is `sandbox`. Capability is declared per kind and is
least-privilege by default:

| kind | scripts | network | iframe |
|---|---|---|---|
| **poster** | **none** | fonts only | `sandbox=""` |
| slides *(later)* | minimal | fonts only | `sandbox="allow-scripts"` |
| app *(later)* | yes | allow-list | `sandbox="allow-scripts"` |

A poster is static art. It has no reason to execute JavaScript, so it is
rendered in an iframe that cannot. That is a stronger posture than ILMUchat's
(a separate origin *with* `allow-same-origin`) and stronger than claude.ai's,
and it costs a field on a dataclass.

The reason to fix this now rather than later: the sandbox contract and the
prompt are coupled. Tell the model it may use a CDN and then tighten the CSP,
and every prompt has to be re-tuned against the new reality.

### 3. The chat model writes a brief, never the poster

The tool takes `{kind, title, brief, style_hints, data}` and refuses code. A
separate call renders the document.

This is the one decision taken unchanged from ILMUchat, because it is the one
that is load-bearing there. It splits *understanding the request* from
*designing the thing*, which means the render step can use a different model, a
16k output budget and a prompt full of design instruction, without any of that
weight riding along in the chat turn's context on every message.

It also makes the chat model's job small and reliable: read the room, write a
brief, hand over.

### 4. Direction before composition, and a refinement pass after

The render is not one call. Claude's own poster skill (`canvas-design`) names
four steps and the order is the point:

> DESIGN PHILOSOPHY CREATION → DEDUCING THE SUBTLE REFERENCE →
> CANVAS CREATION → FINAL STEP

The first step invents a *named aesthetic movement* — "Brutalist Joy",
"Chromatic Silence" — in the abstract, deliberately without naming the poster's
subject. Committing to a direction before knowing the layout is what stops
every poster converging on the same look. The last step is a self-critique that
is forbidden from adding anything: *"If the instinct is to call a new function
or draw a new shape, STOP."*

So:

| step | produces | costs | shown as |
|---|---|---|---|
| brief | the tool call | free | Read the brief |
| **direct** | `DesignSpec` JSON | ~800 tok | Chose a direction · "Midnight Brass" |
| **compose** | streaming HTML | ~16k tok | Composing |
| **validate** | findings | free | Checking it fits |
| **refine** | revised HTML | ~16k tok | Refining |
| repair | revised HTML | ~16k tok | Fixing a problem |

Three things fall out of this that a single call cannot give:

- **The progress panel tells the truth.** ILMUchat's build emits
  `phase: generating | validating` and nothing else, because a single call has
  no interior. Ours has steps because the work has steps.
- **`DesignSpec` is stored.** Re-rendering in a different palette later costs
  no re-reasoning, and "why does it look like that?" is answered by reading a
  row.
- **Refinement cannot degrade the work**, because it may only remove and
  adjust.

`refine` is a setting. It roughly doubles the wall clock, and on a slow provider
someone will want it off.

### 5. Validation is Python, and unknown is not valid

Every check runs in-process against `html.parser`:

| check | fails when |
|---|---|
| structure | unbalanced tags, no root canvas element, truncated output |
| explicit ground | the canvas root sets no background — the classic artifact bug, where the document borrows the host page's colour and text becomes unreadable |
| capability | a `<script>`, an `on*` attribute, an external `src`, a `fetch(` — anything the kind's sandbox forbids |
| images | any raster image; the model cannot produce one, so it can only invent a URL that does not resolve |
| invention | a QR code, a URL, a domain or a social handle nobody supplied |
| fit | text nodes with `white-space: nowrap` on headings, absolute positioning outside the one permitted background layer, a canvas that is not the kind's dimensions |
| size | over `ARTIFACT_MAX_BYTES` |

A failure feeds one repair attempt, with the failing line quoted. The retry is
rebuilt from the original system and user messages rather than appended to the
transcript — ILMUchat learned this the hard way: appending lets a truncation
failure and a validation failure stack into a single incoherent instruction.

### 6. Editing rewrites the document

An edit is a follow-up chat turn. The model is given the current HTML and the
`DesignSpec`, and returns a whole new document, stored as a new version.

Not every edit pays for a call. `DesignSpec` names the palette hexes and the
two font roles, so the cheapest class of edit is a substitution:

| edit | how | cost |
|---|---|---|
| a word on the poster is wrong | edit it in place, in the frame | no model call, instant |
| palette or font swap | replace the spec's hex values and font families in the document | no model call, instant |
| copy, layout, content | one compose call from the spec plus the current HTML — no direction step, no refinement | ~30-50s |
| a new direction entirely | the full pipeline again, as a new artifact | ~40-90s |

The first row works because the spec is stored rather than inferred: "make it
blue" or "try a serif" is a find-and-replace over values we chose deliberately
and wrote down. The second skips two of the four steps because the direction
was settled when the poster was first made, and re-deciding it is how an edit
turns into a different poster.

**Editing text in place.** The commonest edit is a typo, a price or a date,
and going through a model for it is absurd. The panel has an edit mode that
makes the poster's own text directly editable, and saves the result as a new
version like any other edit.

The complication is that a poster renders with scripts disabled, so nothing can
make its text editable from outside — a sandboxed frame is opaque to its
parent, which is the whole point of it. Edit mode therefore re-renders the
frame with `allow-scripts` and a small editor **we** inject: it marks text
nodes `contenteditable`, and posts what changed back over `postMessage`. That
script is ours and is never model output, and the validator already guarantees
the document contains no script of its own, so nothing model-authored ever
executes. The frame still has no `allow-same-origin`, so the editor cannot
reach the app, its cookies or its API either.

The parent applies the returned text by replacing those exact nodes in the
stored HTML. Nothing else in the document is touched, which is what makes this
safe to do without a model checking the result.

The obvious alternative is search-and-replace patching, and Claude's own
artifacts do exactly that today. Two pieces of evidence argue against it for a
first implementation: the original artifacts re-emitted the whole document and
patching was retrofitted a year later, and a patch whose search string does not
match currently [fails silently](https://github.com/anthropics/claude-code/issues/9434)
— the model is told nothing and believes it succeeded. A full rewrite cannot
corrupt a document, costs tokens we are already spending, and leaves the door
open to add patching once the base is boring.

## The prompt

Three assets carry output quality. All three are text, and all three live in
`artifacts/poster.py` next to the kind that uses them.

**Hard invariants.** Nothing clips, nothing overlaps. Layout is flex or grid
with `gap`, never per-element margins. The canvas root sets an explicit
background. At most two font families. Running text near 65 characters.
`text-wrap: balance` on headings, never `nowrap` on a heading that might be
long. One full-bleed background layer may be absolutely positioned; nothing
else may be.

**The slop blocklist**, verbatim, as a negative constraint. It names the tells
with their actual hex values — cream `#F4F1EA` with a serif display and
terracotta `#D97757`; the purple-to-blue gradient hero; identical rounded cards
with one radius and one shadow; Inter as the safe face; centred everything;
tracked-out all-caps eyebrows; `→` appended to link text. It ends with the
escape hatch that makes it safe: **the user's own words always win, including
when they ask for one of these.**

**Craft assertion.** `canvas-design` mandates literal phrases — *meticulously
crafted*, *master-level execution*, *countless hours* — repeated through the
prompt. It is the most distinctive instruction in Claude's corpus and it costs
nothing, so it is in ours.

**Print.** Claude's skills have no print recipe at all — the corpus contains no
`@page`, no `print-color-adjust`, no bleed, no DPI, no millimetre. Screen only.
Ours specifies it: A4 at 96dpi (794×1123), `@page { size: A4; margin: 0 }`,
`print-color-adjust: exact`, so the browser's own print dialogue produces a
correct PDF with no service involved.

## Two protocol changes

Both extend the existing seam rather than branching on it. `CLAUDE.md` promises
the chat service never names a tool, and `test_tool_protocol.py` enforces it —
so, as with `ToolResult.is_image`, behaviour is decided by *shape*.

### Tools receive their arguments

`_run_tool` calls `tool.run(query=…)` today, and `first_argument()` flattens
whatever the model sent into one string (`tools/base.py:71`). That is right for
search and wrong for everything else. Tools receive the parsed argument dict;
`first_argument` survives as what it always was — the fallback for providers
that cannot do function calling.

### Tools may report progress

```python
ToolUpdate = Progress | Delta | Results | Artifact
```

A tool that returns results is adapted into a single `Results` update, so no
existing tool changes. A tool that takes a minute yields `Progress` as it goes.
The service dispatches on the update type, never on the tool.

## Data model

```
artifacts          id · conversation_id · user_id · message_id · kind
                   title · current_version · created_at · updated_at

artifact_versions  id · artifact_id · version · html · design_spec jsonb
                   size_bytes · model · build_ms · prompt_tokens
                   completion_tokens · created_at
                   UNIQUE (artifact_id, version)
```

Version is per artifact, not per conversation. ILMUchat keys it
`UNIQUE(chat_id, version)`, which makes two different artifacts in one
conversation share a counter — a poster and a deck then leapfrog each other's
version numbers for no reason.

Sharing reuses `share_service.py` unchanged in spirit: a 256-bit
`secrets.token_urlsafe(32)`, a frozen copy, an allow-list of public fields,
`noindex` and `no-store`, its own rate-limit bucket, and a revoked token
answering exactly as one that never existed. ILMUchat's artifact slug is
`secrets.token_hex(4)` — 32 bits, which is guessable, and not a mistake to
copy.

## Streaming protocol

Five events, additive as the protocol requires:

```
artifact.start     {artifact_id, kind, title}
artifact.progress  {step, label, detail}
artifact.delta     {text}                      — source view, while composing
artifact.done      {artifact_id, version, size_bytes}
artifact.failed    {reason, message, retryable}
```

`artifact.delta` streams the document into the panel's source view as it is
written. The preview renders once, on `done` — a half-written document renders
as a broken one, and watching a layout thrash is worse than watching code
arrive.

## Frontend

```
components/artifacts/
  ArtifactPanel.tsx      the right panel
  ArtifactFrame.tsx      sandboxed iframe, attributes from the kind
  ArtifactCard.tsx       inline card in the transcript
  BuildSteps.tsx         the live step list
hooks/useArtifact.ts
```

Panel actions: preview ⇄ source, share, open in a new tab, download `.html`,
print to PDF, version switcher, copy, close. The transcript shows a card, never
the source — a poster in a chat bubble is 400 lines of CSS nobody asked for.

## Configuration

New settings in `core/config.py` and `.env.example`, following the `VISION_*`
precedent exactly — its own model, falling back to the main credentials:

```
ARTIFACTS_ENABLED=true
ARTIFACT_MODEL=ilmuchat-artifact    # empty disables the feature
ARTIFACT_BASE_URL=                  # defaults to LLM_BASE_URL
ARTIFACT_API_KEY=                   # defaults to LLM_API_KEY
ARTIFACT_MAX_TOKENS=16384
ARTIFACT_TIMEOUT_SECONDS=300
ARTIFACT_REFINE_PASS=true
ARTIFACT_MAX_BYTES=262144
ARTIFACT_MAX_PER_CONVERSATION=10
```

The gateway already serves `ilmuchat-artifact` (1M context, 128k output) on the
same credentials as the chat model, so this needs no new account and no new
provider. `ilmu-v3.1` itself allows 128k output — the 2048 in `LLM_MAX_TOKENS`
is a default, not a ceiling.

## How to extend it

**A new kind** — slides, a one-page app, a résumé — is one file implementing
`ArtifactKind` and one line in `artifacts/registry.py`. It brings its own
schema fragment, its own prompt, its own canvas and its own sandbox policy. The
tool's `kind` enum is built from the registry, so the model is offered it
automatically.

**A build queue.** Generation runs inside the open SSE stream, which is right
for a single-worker deployment and is what this template is. `Builder` is an
interface; a queued implementation swaps in without touching the tool, the
events or the panel.

**Patch-based editing.** Add it behind the same `edit` entry point once full
rewrite is dull. A non-matching patch must raise loudly and be fed back to the
model — that is the whole lesson from the linked bug.

## Known limits

- **The model cannot make images.** Posters are typography, CSS gradients and
  inline SVG. That is a real constraint on what a poster can be, not a phase.
- **One artifact per turn.** Two would race for the same panel and double the
  turn's cost with no way to show either properly.
- **Refinement doubles the wall clock.** A poster is 40–90 seconds with it on.
- **A content edit costs a compose call.** Only palette and font changes are
  free; anything touching the words or the layout is ~30-50 seconds.
- **Print fidelity is the browser's.** No bleed, no crop marks, no CMYK. A4 at
  96dpi is a screen document that prints well, not a press-ready file.
- **`artifact.delta` shows source, not preview.** There is no progressive
  visual render; the first look at the poster is the finished one.
- **English-only design prompt.** The brief may be in any language and the
  poster's copy follows it, but the design instruction itself is English, in
  line with the existing pattern layers.
- **No queue.** A second concurrent build on one worker competes for the same
  event loop. Fine for a template; the seam is there when it is not.

## Testing

- **Builder** against `FakeProvider` returning canned HTML — the whole pipeline
  without a network call, including each failure path.
- **Validator** unit tests per check, each with a document that fails it and
  one that passes.
- **Prompt assembly pinned by hash**, so a prompt edit shows up as a deliberate
  diff rather than drifting.
- **A kind the codebase has never heard of**, registered by a test and driven
  through tool call, build, persist and panel — the same promise
  `test_tool_protocol.py` already makes for tools.
- **Frontend**: event handling, panel actions, and an assertion on the iframe's
  `sandbox` attribute, because that attribute is the security boundary.
- **In a browser, before it is called done.** `CLAUDE.md` lists three bugs that
  shipped past curl and unit tests. This feature is an iframe, a CSP and a
  print stylesheet — every one of them is a thing that only misbehaves in a
  browser.

## Deliberately not building

A job queue. A template gallery. An OKLCH and colour-blindness palette
validator. A React or Vite bundling step. Remix. Patch-based editing. Each is a
real thing in a bigger system, and each is a subsystem this one does not need
to prove it works.
