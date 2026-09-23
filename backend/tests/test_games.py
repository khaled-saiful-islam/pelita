"""Designing, checking and playing a game."""

from __future__ import annotations

import pytest

from app.artifacts.base import Brief, SandboxPolicy
from app.artifacts.game_prompts import DEFAULT_LEVELS, MAX_LEVELS
from app.artifacts.games import GamesKind, _read_design, _script_of, wanted_levels
from app.artifacts.playtest import Playtest


def brief(text: str = "", *, count: int = 0, title: str = "A game") -> Brief:
    return Brief(kind="games", title=title, brief=text, count=count)


def kind() -> GamesKind:
    return GamesKind(None, playtest=False)  # type: ignore[arg-type]


# --- how many levels ----------------------------------------------------


def test_the_number_the_person_gave_wins() -> None:
    assert wanted_levels(brief("snake", count=3)) == 3


def test_a_number_in_the_brief_is_the_fallback() -> None:
    assert wanted_levels(brief("a snake game with 5 levels")) == 5
    assert wanted_levels(brief("three rounds")) == DEFAULT_LEVELS  # words are not numbers
    assert wanted_levels(brief("a game of 4 stages")) == 4


def test_no_number_means_three() -> None:
    assert wanted_levels(brief("a snake game")) == DEFAULT_LEVELS


@pytest.mark.parametrize(("asked", "given"), [(0, DEFAULT_LEVELS), (99, MAX_LEVELS)])
def test_a_silly_number_is_brought_back_into_range(asked: int, given: int) -> None:
    assert wanted_levels(brief("x", count=asked)) == given


# --- the sandbox --------------------------------------------------------


def test_a_game_may_run_scripts_and_nothing_else_may() -> None:
    from app.artifacts.poster import PosterKind
    from app.artifacts.slides import SlidesKind

    assert GamesKind.sandbox.iframe_sandbox == "allow-scripts"
    assert PosterKind.sandbox.iframe_sandbox == ""
    assert SlidesKind.sandbox.iframe_sandbox == ""


def test_a_game_never_gets_the_origin_it_was_framed_from() -> None:
    """`allow-scripts` without `allow-same-origin` is an opaque origin: the
    game runs, and can reach neither a cookie nor this API with one."""
    assert "allow-same-origin" not in GamesKind.sandbox.iframe_sandbox
    assert "allow-same-origin" not in GamesKind.sandbox.csp


def test_a_game_cannot_phone_home() -> None:
    assert "connect-src 'none'" in GamesKind.sandbox.csp


def test_a_scripted_document_can_actually_run_its_own_scripts() -> None:
    """`script-src https:` permits every origin on the web and no inline
    script at all, so the document would not have run when served on its own."""
    csp = SandboxPolicy(scripts=True).csp
    assert "script-src 'unsafe-inline'" in csp
    assert "script-src https:" not in csp


def test_a_static_kind_still_runs_nothing() -> None:
    assert "script-src 'none'" in SandboxPolicy(scripts=False).csp


# --- what can be known without running it --------------------------------


PLAYABLE = """<!DOCTYPE html>
<html><head><style>canvas{background:#111}</style></head>
<body><canvas id="c" width="900" height="640"></canvas>
<script>
const c = document.getElementById('c').getContext('2d');
let x = 0;
addEventListener('keydown', (e) => { x += 4; e.preventDefault(); });
function frame() { c.fillStyle = '#e2b'; c.fillRect(x, 20, 40, 40); requestAnimationFrame(frame); }
frame();
</script></body></html>"""


def test_a_working_game_has_nothing_to_report() -> None:
    assert kind()._check(PLAYABLE) == ()


def test_a_blocking_loop_is_refused_before_a_browser_is_spent_on_it() -> None:
    """It does not throw, it hangs: the tab stops answering and the person
    closes it. Cheaper to catch by reading than by playing."""
    frozen = PLAYABLE.replace("frame();", "while (true) { x++; }")
    assert any("freeze" in str(f) for f in kind()._check(frozen))


def test_a_game_that_reaches_the_network_is_refused() -> None:
    reaching = PLAYABLE.replace("let x = 0;", "let x = 0; fetch('https://example.test/score');")
    assert any("self-contained" in str(f) for f in kind()._check(reaching))


def test_a_game_that_loads_a_script_from_elsewhere_is_refused() -> None:
    borrowed = '<script src="https://cdn.test/engine.js"></script><script>'
    linked = PLAYABLE.replace("<script>", borrowed)
    assert any("from elsewhere" in str(f) for f in kind()._check(linked))


def test_a_game_with_no_loop_is_not_a_game() -> None:
    still = PLAYABLE.replace("requestAnimationFrame(frame); ", "")
    assert any("no loop" in str(f) for f in kind()._check(still))


def test_a_game_that_reads_no_input_cannot_be_played() -> None:
    listener = "addEventListener('keydown', (e) => { x += 4; e.preventDefault(); });"
    deaf = PLAYABLE.replace(listener, "")
    assert any("cannot be played" in str(f) for f in kind()._check(deaf))


def test_only_the_scripts_are_searched_for_banned_calls() -> None:
    """A game about network security may say `fetch` in its own text without
    calling it."""
    prose = PLAYABLE.replace("<body>", "<body><p>Avoid fetch() in hot loops</p>")
    assert "Avoid fetch()" not in _script_of(prose)
    assert kind()._check(prose) == ()


# --- reading the design --------------------------------------------------


DESIGNED = """NAME: Depth Charge
LOOP: Drop charges on the sub before it reaches the harbour.
PRESSURE: The sub gets faster every time you miss.
CONTROLS: Left and right arrows, space to drop. Tap either half on touch.
PALETTE: #06131f, #0d2f45, #f2e8d5, #d9534f
DISPLAY: Space Mono
BODY: Work Sans
FEEL: Cold sonar greens against a warm alarm red.
---LEVELS---
[{"name": "Shallows", "changes": {"speed_ms": 160}},
 {"name": "Open water", "changes": {"speed_ms": 120}}]
"""


def test_the_design_is_read_off_the_header_lines() -> None:
    design = _read_design(DESIGNED)

    assert design.name == "Depth Charge"
    assert design.loop.startswith("Drop charges")
    assert design.display_font == "Space Mono"
    assert design.palette == ("#06131f", "#0d2f45", "#f2e8d5", "#d9534f")


def test_the_levels_come_back_with_their_numbers() -> None:
    """"Faster" is not a level. The tick in milliseconds is."""
    levels = _read_design(DESIGNED).levels

    assert len(levels) == 2
    assert levels[0]["changes"]["speed_ms"] == 160
    assert levels[1]["changes"]["speed_ms"] == 120


def test_a_design_with_no_levels_is_not_usable() -> None:
    assert _read_design(DESIGNED.split("---LEVELS---")[0]).levels == ()


def test_broken_level_json_does_not_lose_the_rest_of_the_design() -> None:
    design = _read_design(DESIGNED.replace('"speed_ms": 160}},', '"speed_ms": }},'))

    assert design.name == "Depth Charge"
    assert design.levels == ()


# --- what playing it found ------------------------------------------------


def test_a_game_that_ran_cleanly_has_no_complaints() -> None:
    assert Playtest().ok
    assert Playtest().complaints() == []


def test_an_exception_is_the_first_thing_reported() -> None:
    """Everything else is usually its consequence."""
    result = Playtest(errors=("ReferenceError: draw is not defined",), painted=False)

    assert not result.ok
    assert "ReferenceError" in result.complaints()[0]


def test_a_game_that_drew_nothing_is_a_complaint() -> None:
    assert any("rendered nothing" in c for c in Playtest(painted=False).complaints())


def test_a_game_that_stopped_after_one_frame_is_a_complaint() -> None:
    assert any("stopped" in c for c in Playtest(loops=False).complaints())


def test_a_game_reaching_the_network_is_reported_with_where() -> None:
    result = Playtest(reached_network=("https://example.test/score",))
    assert any("example.test" in c for c in result.complaints())


def test_reaching_the_network_alone_does_not_make_a_game_broken() -> None:
    """It is worth telling the model about, but a game whose leaderboard call
    was refused still plays."""
    assert Playtest(reached_network=("https://example.test/x",)).ok


# --- the counter the playtest runs on ------------------------------------


def test_the_counter_goes_in_front_of_the_game() -> None:
    """`add_init_script` runs at document-start of a navigation, so
    `set_content` rewriting the document wiped it: the counter read
    `undefined` every time and every game looked stopped."""
    from app.artifacts.playtest import _counting

    counted = _counting(PLAYABLE)
    assert counted.index("window.__frames") < counted.index("<canvas")
    assert PLAYABLE.split("<body>")[1] in counted


def test_a_fragment_with_no_head_still_gets_counted() -> None:
    from app.artifacts.playtest import _counting

    assert _counting("<div>hi</div>").startswith("<script>")


def test_a_timer_driven_game_counts_as_running() -> None:
    """A game does not have to use requestAnimationFrame to be a game."""
    from app.artifacts.playtest import _COUNTER

    assert "setInterval" in _COUNTER


def test_the_design_becomes_a_spec_the_panel_can_show() -> None:
    """The first real build died here: a palette became `Swatch(hex=...)` and
    `Swatch` takes a name too. Nothing in these tests had called it."""
    from app.artifacts.games import _spec_of

    spec = _spec_of(_read_design(DESIGNED))

    assert spec.movement == "Depth Charge"
    assert spec.display_font == "Space Mono"
    assert [s.hex for s in spec.palette] == ["#06131f", "#0d2f45", "#f2e8d5", "#d9534f"]
    assert [s.name for s in spec.palette][:2] == ["ground", "ink"]


def test_a_palette_longer_than_the_named_roles_still_works() -> None:
    from app.artifacts.games import _named

    named = _named(tuple(f"#00000{i}" for i in range(8)))
    assert len(named) == 8
    assert all(s.name for s in named)


# --- the whole build ------------------------------------------------------


class FakeGameModel:
    """Answers the design call, then the writing call, then any fixes."""

    name = "fake-artifact"

    def __init__(self, design: str, documents: list[str]) -> None:
        self._replies = [design, *documents]
        self.systems: list[str] = []

    async def write(self, system, user, into, *, temperature=None):
        self.systems.append(system)
        into.text = self._replies.pop(0) if self._replies else ""
        yield into.text


async def built(kind_under_test, text: str = "snake, 3 levels") -> list:
    return [u async for u in kind_under_test.build(brief(text, count=3))]


async def test_a_game_is_built_end_to_end() -> None:
    """The first real build died between the design and the document, in code
    no unit test here had called. This walks the whole path."""
    model = FakeGameModel(DESIGNED, [PLAYABLE])
    updates = await built(GamesKind(model, playtest=False))  # type: ignore[arg-type]

    finished = updates[-1].built
    assert finished.html.startswith("<!DOCTYPE html>")
    assert finished.findings == ()
    assert finished.spec.movement == "Depth Charge"
    assert finished.spec.width == 900 and finished.spec.height == 640


async def test_the_design_reaches_the_writing_call() -> None:
    """Otherwise the levels were decided and then quietly ignored."""
    model = FakeGameModel(DESIGNED, [PLAYABLE])
    await built(GamesKind(model, playtest=False))  # type: ignore[arg-type]

    writing = model.systems[1]
    assert "Depth Charge" in writing
    assert "speed_ms" in writing
    assert "160" in writing


async def test_the_look_is_announced_before_the_game_is_written() -> None:
    """The panel shows it in its own colours while it waits."""
    model = FakeGameModel(DESIGNED, [PLAYABLE])
    updates = await built(GamesKind(model, playtest=False))  # type: ignore[arg-type]

    designed = [u for u in updates if type(u).__name__ == "Designed"]
    assert designed and designed[0].palette[0] == "#06131f"


async def test_a_game_that_never_arrives_is_refused_not_stored() -> None:
    model = FakeGameModel(DESIGNED, [""])
    with pytest.raises(Exception, match="could not be written"):
        await built(GamesKind(model, playtest=False))  # type: ignore[arg-type]


async def test_a_design_with_no_levels_stops_the_build() -> None:
    thin = DESIGNED.split("---LEVELS---")[0]
    model = FakeGameModel(thin, [thin, PLAYABLE])
    with pytest.raises(Exception, match="what this game should be"):
        await built(GamesKind(model, playtest=False))  # type: ignore[arg-type]


async def test_a_broken_game_is_reported_rather_than_shown_as_fine() -> None:
    """Static checks run even when there is no browser to play in."""
    frozen = PLAYABLE.replace("frame();", "while (true) { x++; }")
    model = FakeGameModel(DESIGNED, [frozen])
    updates = await built(GamesKind(model, playtest=False))  # type: ignore[arg-type]

    assert any("freeze" in f for f in updates[-1].built.findings)


def test_a_game_that_wedges_the_browser_is_the_worst_result_not_a_pass() -> None:
    """A real generation sat for five minutes with Chromium still running and
    nothing coming back: the probe has no timeout of its own, so a game that
    blocks its own thread blocked the build, the stream and the turn."""
    frozen = Playtest(froze=True, painted=False, loops=False)

    assert not frozen.ok
    assert "locked up the browser" in frozen.complaints()[0]


def test_the_freeze_is_reported_before_anything_it_caused() -> None:
    frozen = Playtest(froze=True, painted=False, loops=False)
    assert "locked up" in frozen.complaints()[0]
    assert len(frozen.complaints()) > 1  # the blank screen is still mentioned


def test_the_playtest_is_bounded() -> None:
    from app.artifacts.playtest import BUDGET_S, PROBE_S

    assert 0 < BUDGET_S <= 60
    assert 0 < PROBE_S <= 10


def test_the_probe_is_bounded_from_outside_not_by_an_argument() -> None:
    """`page.evaluate` has no `timeout` parameter; passing one is a TypeError
    that fires on every game that gets as far as being probed."""
    import inspect

    from app.artifacts import playtest

    body = inspect.getsource(playtest._run)
    assert "page.evaluate(_PROBE)" in body
    assert "evaluate(_PROBE, timeout" not in body
    assert body.count("asyncio.wait_for(page.evaluate(_PROBE)") == 2


# --- noise the playtest makes itself --------------------------------------


def test_a_refused_request_is_not_the_games_fault() -> None:
    """Chromium logs `net::ERR_FAILED` for every resource this playtest
    blocks. Counted as errors, they sent a working game back to be "fixed" —
    every single time, because the prompt asks for a font link."""
    from app.artifacts.playtest import _REFUSED

    assert _REFUSED.search("Failed to load resource: net::ERR_FAILED")
    assert _REFUSED.search("net::ERR_FAILED")
    assert not _REFUSED.search("ReferenceError: draw is not defined")
    assert not _REFUSED.search("Uncaught TypeError: cannot read 'x' of undefined")


def test_the_faces_the_prompt_asks_for_are_let_through() -> None:
    """Blocking them tests a different game from the one that ships: the same
    game rendered entirely in the fallback face."""
    from app.artifacts.playtest import _FONTS

    assert _FONTS.match("https://fonts.googleapis.com/css2?family=Orbitron")
    assert _FONTS.match("https://fonts.gstatic.com/s/orbitron/v31/font.woff2")
    assert not _FONTS.match("https://example.test/score")
    assert not _FONTS.match("https://fonts.googleapis.com.evil.test/x")
