"""What the model is told when it builds a deck.

Three prompts, because a deck is three different jobs. Deciding what the talk
is about is not the same as deciding what it looks like, and neither is the
same as writing one slide well — and a model asked to do all three at once does
the third one badly, every time.

The outline is where a deck is won or lost. Ten headings in a row is not a
talk; it is a table of contents read aloud.
"""

from __future__ import annotations

# Five, not ten. A deck nobody asked a size for is one somebody is waiting on,
# and ten slides is two minutes of waiting for twice the deck they wanted.
# Asking for more is one sentence; waiting is not.
DEFAULT_SLIDES = 5
MIN_SLIDES = 3
MAX_SLIDES = 24

# How many grounds a deck may move between. The names are the design's own —
# a deck about kopi and a deck about quarterly churn should not be reaching
# into the same box of three tones — so only the count is fixed here.
MIN_GROUNDS = 2
MAX_GROUNDS = 4

# Enough for a sentence to breathe, few enough that nobody reads the slide
# instead of listening. Checked, not merely asked for.
MIN_WORDS = 12
MAX_WORDS = 55

OUTLINE_SYSTEM = """
You are planning a talk, not filling in a template.

Decide what the talk actually argues, then break it into slides that get it
there. A reader should be able to follow the argument from the outline alone.
Ten headings in a row is a table of contents; a talk has a shape — something
established, something complicated, something resolved.

For each slide say what job it does, and pick the layout that does that job:

- `title`      the opening. The name of the talk and one line that frames it.
- `agenda`     what is coming. Only in a deck long enough to need one.
- `statement`  one idea, large. For the turn of the argument.
- `points`     three or four parallel items. Never more than four.
- `split`      two things side by side: before and after, problem and answer.
- `compare`    a real comparison, two or three columns with the same rows.
- `data`       a number that matters, given room, with its source and meaning.
- `quote`      someone's words, when whose words they are is the point.
- `process`    ordered steps, numbered, when sequence is the content.
- `image`      a photograph doing work no arrangement of type could do.
- `closing`    what to take away and what to do next.

Rules that matter:
- Never the same layout three times running. A deck of ten `points` slides is
  the most boring object in professional life.
- `title` first and `closing` last, always.
- Every slide needs a reason to exist. If two slides make the same point, they
  are one slide.
- `speaker_notes` is what the presenter says and the slide does not show — one
  or two sentences, never a reading of the slide.
- `image_query` only where a photograph genuinely earns its place, and never on
  more than a third of the slides. Concrete search terms, not a description of
  the slide.

Reply with JSON and nothing else:

{"title": "the name of the talk",
  "subtitle": "one line",
  "argument": "one sentence: what this talk claims",
  "slides": [
    {"heading": "what this slide says",
      "layout": "one of the layouts above",
      "job": "what it does for the argument",
      "content": "the substance, in prose - the writer turns this into the slide",
      "speaker_notes": "what the presenter adds",
      "image_query": "search terms, or empty"}
  ]}
"""

# The stylesheet is asked for after a marker rather than inside a JSON string.
# A deck's CSS is full of quotes and newlines -- `font-family: "Lora"`,
# `content: "01"` -- and a model escaping all of that into one JSON value gets
# it wrong often enough that whole decks were lost to a parse error.
CSS_MARKER = "---CSS---"

DESIGN_SYSTEM = f"""
You are choosing how a deck looks, before any slide is written.

Name the direction in one or two words, as a small art movement would be named,
and let the subject decide it. A deck about coral reefs and a deck about
quarterly churn are not the same object, and neither is black text on white.

Write a stylesheet that every slide will share. It must define:

- `:root` custom properties for a palette of five to seven named colours: a
  ground, two or three inks with different weight, one accent that carries
  emphasis, and one quiet tone for rules and captions. Deliberate, not default.
  Never plain black on plain white; never a black deck either, unless the
  subject actually calls for it.
- Two font families from Google Fonts, chosen for the subject: a display face
  with character and a body face that stays readable at a distance.
- `.slide` -- the slide surface itself, exactly the width and height given,
  `overflow: hidden`, `position: relative`, `display: flex`, with generous
  padding. Every slide is this size.
- Classes for each layout the outline asked for: `.slide--title`,
  `.slide--points` and so on, each doing its job properly rather than all
  looking alike.
- **Grounds the deck moves between** -- {MIN_GROUNDS} to {MAX_GROUNDS} of
  them -- because a deck where every slide is the same colour reads as one
  long slide. Name them yourself, after this subject: a deck about deep-sea
  vents and a deck about a bakery should not be reaching into the same box
  of tones. Each is a class of your own naming, sets its own background AND
  its own ink, and every layout must stay readable on all of them. They are
  put on the slides for you -- list them on the GROUNDS line below, the one
  for the moments that should land first.
- Type scale, `h1` through `p`, a `.eyebrow`, a `.caption`, a `.note`.
- At least one recurring graphic device -- a rule, a corner mark, a numeral, a
  shape -- that makes the deck look like one deck.

Not these, whatever the subject:
- Inter, Space Grotesk or Helvetica as either face. They are what gets reached
  for when nothing has been decided, and a deck set in them looks like every
  other deck.
- Plain white ground with near-black text, or the same inverted. Two defaults
  are not a palette.
- A purple-to-blue gradient behind the title.
- One radius and one faint shadow on every box, so every element reads as the
  same kind of object.
- Tracked-out all-caps eyebrows above every heading.
If the person asked for one of these in their own words, they get it. Their
words win.

Hard constraints:
- No scripts, no image URLs, no window units (vh, vw, vmin, vmax) anywhere.
- Slide numbers via CSS counters, never typed into each slide by hand.
- Every colour below `:root` refers to a variable. Never repeat a literal hex.

Reply in exactly this shape. Five header lines, then the marker on a line of
its own, then the stylesheet as plain CSS. No JSON, no code fence, no
commentary.

MOVEMENT: two words at most
DISPLAY: a Google Fonts family
BODY: a Google Fonts family
GROUNDS: your ground class names, comma separated, emphatic one first
WHY: one sentence on why this suits the subject
{CSS_MARKER}
:root {{ ... }}
.slide {{ ... }}
"""

SLIDE_SYSTEM = f"""
You are writing one slide of a deck that already has a look.

The stylesheet exists and is given to you. Use its classes. Do not restate it,
do not add a `<style>` block, and do not invent new colours — everything you
need is already defined.

Return only the slide's markup: a single `<section class="slide slide--LAYOUT">`
element and its contents. No document, no head, no body, no commentary.

What makes a slide good:
- **Say one thing.** A slide with two ideas is two slides.
- **Between {MIN_WORDS} and {MAX_WORDS} words.** Fewer is a poster; more is a
  document nobody reads while somebody talks over it.
- Write in **full, confident phrases**. Not bullet fragments padded with "the",
  not sentences that trail off.
- The heading carries the point. If the heading is "Results" and the body
  explains what they were, the heading is wasted.
- Numbers get room and units. A figure in a paragraph is a figure nobody sees.
- Use the layout's structure. A `points` slide is three or four parallel items,
  not a paragraph with line breaks.
- Inline `<svg>` icons and CSS shapes are welcome where they clarify. Decoration
  that clarifies nothing is noise.
- Nothing may overflow the slide. Fewer, larger words beat more, smaller ones.

Never write an image URL. If a photograph was found for this slide you are told
so and given the variable that holds it; that is the only image there is.

Reply with the `<section>` element and nothing else.
"""


DECK_CHANGE_SYSTEM = """
Somebody wants one thing different about a deck that already exists. Work out
which of three things they are asking for, and reply with JSON and nothing
else.

To change what is on the slides — a colour, a word, a heading, a layout:

{"action": "edit",
 "edits": [{"find": "exact text from the document", "replace": "what it becomes"}]}

`find` must be copied character for character out of the document and appear
exactly once in it. Make as few edits as the change needs, and never restate
the whole document as one edit. Everything not named stays exactly as it is:
they are looking at a deck they largely like.

To add a slide:

{"action": "add", "after": 3, "heading": "what it says",
 "layout": "one of: title, agenda, statement, points, split, compare, data,
 quote, process, image, closing", "content": "the substance, in prose",
 "speaker_notes": "what the presenter adds"}

`after` is the number of the slide it follows, counting from 1. Zero puts it
first.

To remove slides:

{"action": "remove", "slides": [4]}

Numbered from 1. Removing the only slide is not a change anybody wants.
"""
