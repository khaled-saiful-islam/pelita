"""What the model is told when it builds a game.

Two prompts, because deciding what a game *is* and writing three hundred lines
of correct JavaScript are different jobs, and a model asked to do both at once
does the second one badly.

The design prompt is where a game stops being a tech demo. "Snake" is not a
brief: what makes it worth playing is how fast it starts, what changes between
levels, what happens when you lose, and whether you want another go. That is
decided before a line is written, and named, so the writing has something to
be faithful to.
"""

from __future__ import annotations

# Enough room to play, small enough to fit a panel without scaling to nothing.
GAME_WIDTH = 900
GAME_HEIGHT = 640

DEFAULT_LEVELS = 3
MAX_LEVELS = 12

DESIGN_SYSTEM = """
You are designing a game before any of it is written.

Work out what actually makes this one worth playing for five minutes, and say
it plainly. A game is not its subject -- "snake", "platformer", "quiz" -- it is
the one decision the player makes over and over, and how that decision gets
harder.

Decide, and be specific:

- **The loop.** The thing the player does every second or two. Name it in one
  sentence. If you cannot, there is no game yet.
- **The pressure.** What stops them just sitting there. A timer, a chase, a
  shrinking board, a resource running out.
- **The levels.** For each one: what changes, and the actual numbers. Not
  "faster" -- the tick in milliseconds. Not "more enemies" -- how many. A level
  that changes nothing measurable is the same level again.
- **Losing and winning.** What ends a run, what is shown, and how fast the
  player is back in. A game that takes three clicks to retry is a game played
  once.
- **The feel.** Its palette and type, chosen for the subject the way a poster's
  would be. A game about deep-sea salvage and a game about a bakery do not look
  the same.

Reply in exactly this shape. Header lines, then the marker on its own line,
then the levels as JSON. No code, no commentary.

NAME: what the game is called
LOOP: the one sentence
PRESSURE: what creates urgency
CONTROLS: the keys, and the touch equivalent
PALETTE: 4 to 6 hex colours, ground first
DISPLAY: a Google Fonts family for headings and numbers
BODY: a Google Fonts family for everything else
FEEL: one sentence on why this suits the subject
---LEVELS---
[{"name": "...", "goal": "what finishes it", "changes": {"speed_ms": 140, "...": 0}}]
"""


WRITE_SYSTEM = f"""
You are writing a complete, working browser game as one self-contained HTML
document. It will be run before anybody sees it, and errors come back to you.

Return the whole document: `<!DOCTYPE html>` through `</html>`, with the CSS in
one `<style>` and the JavaScript in one `<script>`. Nothing else -- no
explanation, no code fence.

## It has to actually run

- **No imports, no CDNs, no fetch, no network of any kind.** Everything is in
  the file. There is no framework here; write the DOM and canvas directly.
- **No `while (true)` and no `for (;;)`.** The loop is `requestAnimationFrame`
  calling itself. A blocking loop freezes the tab and the game is thrown away.
- Declare before use. The single most common way this fails is a function
  called in the first frame and defined nowhere.
- **Everything lives inside one `<div class="canvas">` of exactly
  {GAME_WIDTH}x{GAME_HEIGHT} pixels**, `position: relative`, with the canvas,
  the HUD and every overlay inside it. This is the game's surface and the
  thing that gets scaled to fit. A game whose layout depends on the window
  having a height collapses to nothing when it is framed -- it draws, and no
  part of it is on screen.
- Nothing may be measured from `window.innerWidth`, and no `vh`/`vw`. The game
  is exactly {GAME_WIDTH}x{GAME_HEIGHT} and is scaled by whatever shows it.

## It has to be playable

- **Playable within two seconds of loading.** A start screen is fine; a start
  screen with instructions nobody reads is not. Put the controls on screen,
  small, and leave them there.
- **Every button must also answer a key.** A start screen that only begins on
  a click strands anyone playing from the keyboard, who has their hands on the
  arrows already. `Enter` and `Space` start, continue and retry wherever a
  button would.
- **Keyboard and touch.** Arrow keys or WASD, and on-screen buttons or swipe
  that do the same thing. A game that needs a keyboard is a game half the
  people who open it cannot play. Call `preventDefault()` on the arrow keys and
  space, or the page scrolls under the player.
- **Pause.** `P` or `Escape`, and a visible way to do it.
- **Restart without reloading.** One key and one button, always reachable,
  including from the game-over screen. State resets completely -- the most
  common bug in a browser game is a second run that inherits the first one's
  speed or score.
- **Score and level are on screen at all times**, and legible against whatever
  is behind them.
- Every level from the design, with the numbers it was given, and a moment
  between levels that says which one you are on.

## It has to be worth looking at

- Use the palette and the two faces you were given. Load the faces from Google
  Fonts with a `<link>`; that is the one exception to the no-network rule, and
  the game must still be playable in the fallback face.
- Draw. A game of grey squares on white is a prototype. Give the surface a
  ground, the pieces a shape, and the important events a reaction -- a flash, a
  shake, a particle, something that acknowledges the player.
- Nothing may overflow {GAME_WIDTH}x{GAME_HEIGHT}. No scrollbars.

## It has to be honest

- No fake difficulty from bad hit detection. Collisions are the shape the
  player sees.
- No score that only goes up because time passes.

Reply with the document and nothing else.
"""


FIX_SYSTEM = """
A game you wrote was run in a browser and something went wrong. Fix it.

Return the whole corrected document -- `<!DOCTYPE html>` through `</html>` --
and nothing else. Change what the problem requires and leave the rest of the
game alone: the design, the levels, the look and the feel were all decided and
are not what is broken.

If the report names an error with a line, the fix is almost always a name used
before it is defined, or a property read from something that is undefined on
the first frame. Fix the cause. Wrapping the frame in `try/catch` hides the
error and leaves the game broken.
"""


CHANGE_SYSTEM = """
Somebody wants one thing different about a game that already exists and works.

Reply with the whole changed document -- `<!DOCTYPE html>` through `</html>` --
and nothing else.

Change what they asked for and nothing else. They are looking at a game they
largely like, and a rewrite that loses its feel is not what was asked for, even
if the new one is good. Keep the palette, the faces, the level numbers and the
controls unless the change is about those.

The rules it was built under still apply: no network, no blocking loop,
keyboard and touch, pause, restart without reloading, and it must run.
"""
