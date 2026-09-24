"""Designing, running, remembering and checking an app.

The runtime and the design are strings and tested as strings. What an app
keeps is tested through the API. And the parts that are behaviour -- saving
through the panel, a broken button being caught -- are proved in the same
Chromium the builds use.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.artifacts.app_runtime import app_id_of, instrument, strip_runtime, with_state
from app.artifacts.apptest import AppCheck
from app.artifacts.base import Brief
from app.artifacts.text_edit import readable_text
from app.artifacts.web_app import AppKind, read_design
from app.db.models.conversation import Conversation
from app.db.repositories.artifacts import SqlArtifactRepository

APP = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tally</title>
<style>
main { font-family: sans-serif; padding: 24px; max-width: 600px; margin: 0 auto; }
li { padding: 6px 0; }
</style>
</head>
<body>
<main id="app">
  <h1>Tally</h1>
  <form id="add"><label>Task <input id="task" required></label>
    <button type="submit">Add</button></form>
  <ul id="list"></ul>
  <p id="empty">Nothing yet. Add the first thing you need to do.</p>
  <button id="clear" type="button">Clear done</button>
</main>
<script>
const state = PelitaStore.load({ tasks: [] });
const list = document.getElementById('list');
function render() {
  list.innerHTML = '';
  state.tasks.forEach((t) => {
    const li = document.createElement('li'); li.textContent = t; list.appendChild(li);
  });
  document.getElementById('empty').hidden = state.tasks.length > 0;
}
document.getElementById('add').addEventListener('submit', (e) => {
  e.preventDefault();
  const input = document.getElementById('task');
  state.tasks.push(input.value); input.value = '';
  PelitaStore.save(state); render();
});
document.getElementById('clear').addEventListener('click', () => {
  state.tasks = []; PelitaStore.save(state); render();
});
render();
</script>
</body>
</html>"""


# --- the design ---------------------------------------------------------------

DESIGNED = """NAME: Tally
DIRECTION: soft paper planner
JOB: Keep today's tasks in one short list you can clear in a tap.
FOR: a student with too many tabs open
CORE: add a task | tick it off | clear what is done | undo a clear
KEEPS: the tasks and what is done
FIRST: three sample tasks, one already ticked
DELIGHT: a ticked task strikes through with a soft ink line
KEYS: N for a new task, Escape to cancel
PALETTE: #f7f1e3, #2b2a28, #c2410c, #e9dfc7
DISPLAY: Fraunces
BODY: Work Sans
FEEL: paper and ink, because a to-do list is a thing you write
"""


def test_the_design_is_read_off_its_lines() -> None:
    design = read_design(DESIGNED)
    assert design.name == "Tally"
    assert design.core == ("add a task", "tick it off", "clear what is done", "undo a clear")
    assert design.palette[0] == "#f7f1e3"
    assert design.display_font == "Fraunces"


def test_a_design_with_nothing_in_it_is_not_usable() -> None:
    design = read_design("Sure! Here is an app.")
    assert not design.job and not design.core


def test_a_thin_palette_falls_back_rather_than_failing() -> None:
    design = read_design(
        DESIGNED.replace("PALETTE: #f7f1e3, #2b2a28, #c2410c, #e9dfc7", "PALETTE: warm")
    )
    assert len(design.palette) >= 3


# --- the sandbox --------------------------------------------------------------


def test_an_app_may_run_scripts_and_hear_its_own_forms() -> None:
    assert AppKind.sandbox.iframe_sandbox == "allow-scripts allow-forms"


def test_an_app_never_gets_the_origin_it_was_framed_from() -> None:
    """Which is why the panel saves on its behalf: it cannot call the API."""
    assert "allow-same-origin" not in AppKind.sandbox.iframe_sandbox
    assert "connect-src 'none'" in AppKind.sandbox.csp
    assert "form-action 'none'" in AppKind.sandbox.csp


# --- the runtime --------------------------------------------------------------


def test_the_store_is_defined_before_the_apps_own_script() -> None:
    document = instrument(APP, "a1b2c3d4e5f6")
    assert document.index('data-pelita="store"') < document.index("PelitaStore.load(")
    assert document.index('data-pelita="store"') < document.index("<meta")


def test_the_guard_comes_after_the_apps_own_styles() -> None:
    document = instrument(APP, "a1b2c3d4e5f6")
    assert document.index('data-pelita="app"') > document.index("max-width: 600px")


def test_an_app_keeps_its_id_however_many_times_it_is_changed() -> None:
    """The id is how a downloaded copy finds what it saved."""
    once = instrument(APP, "a1b2c3d4e5f6")
    twice = instrument(once)
    assert app_id_of(twice) == "a1b2c3d4e5f6"
    assert twice.count('data-pelita="store"') == 1
    assert twice.count('data-pelita="app"') == 1


def test_the_runtime_comes_back_out_exactly() -> None:
    assert strip_runtime(instrument(APP, "a1b2c3d4e5f6")) == APP


def test_saved_data_cannot_end_the_script_it_is_put_into() -> None:
    document = with_state(APP, {"tasks": ["</script><script>alert(1)</script>"]})
    tag = document[document.index('data-pelita="state"') :]
    assert tag.index("</script>") > tag.index("__PELITA_STATE__")
    assert "\\u003c/script>" in tag


def test_saved_data_comes_before_the_store_that_reads_it() -> None:
    document = with_state(instrument(APP, "a1b2c3d4e5f6"), {"tasks": []})
    assert document.index('data-pelita="state"') < document.index('data-pelita="store"')


# --- what can be known without running it ------------------------------------


def kind() -> AppKind:
    return AppKind(None, check=False)  # type: ignore[arg-type]


def test_a_working_app_has_nothing_to_report() -> None:
    assert kind()._static(instrument(APP)) == ()


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ("PelitaStore.save(state); render();\n});", "alert('Added'); });"),
        (
            "const state = PelitaStore.load({ tasks: [] });",
            "const state = JSON.parse(localStorage.getItem('t') || '{}');",
        ),
        ("render();\n</script>", "fetch('/api/tasks'); render();\n</script>"),
    ],
)
def test_what_will_not_work_where_it_is_shown_is_named(change: str, said: str) -> None:
    broken = APP.replace(change, said)
    assert broken != APP
    assert kind()._static(instrument(broken))


def test_an_app_outside_its_root_is_named() -> None:
    assert any("main id" in str(f) for f in kind()._static(APP.replace('id="app"', "")))


def test_the_runtime_itself_is_not_mistaken_for_the_app_using_storage() -> None:
    """The runtime touches `localStorage` for a downloaded copy. That is ours,
    and must not read as the app breaking the rule."""
    assert kind()._static(instrument(APP)) == ()


# --- words the pencil can change ---------------------------------------------


def test_a_template_is_not_counted_as_words_on_the_page() -> None:
    """The browser editing the words never walks a template's contents. Counted
    here, every run after it would be off by the runs inside."""
    document = "<body><h1>Title</h1><template><li>Row</li></template><p>After</p></body>"
    assert readable_text(document) == ["Title", "After"]


# --- the check's verdicts ----------------------------------------------------


def test_a_clean_app_has_no_complaints() -> None:
    assert AppCheck().ok and AppCheck().complaints() == []


def test_a_dialog_is_a_complaint_because_the_panel_blocks_it() -> None:
    complaint = AppCheck(dialogs=("confirm",)).complaints()[0]
    assert "confirm()" in complaint and "in the page" in complaint


def test_an_error_while_using_it_comes_first() -> None:
    result = AppCheck(errors=("tasks is not defined",), wide=("div.board runs 80px past",))
    assert "tasks is not defined" in result.complaints()[0]


# --- the whole build, against a fake model -----------------------------------


class FakeAppModel:
    name = "fake-artifact"

    def __init__(self, design: str, documents: list[str]) -> None:
        self._replies = [design, *documents]
        self.systems: list[str] = []

    async def write(self, system, user, into, *, temperature=None):
        self.systems.append(system)
        into.text = self._replies.pop(0) if self._replies else ""
        yield into.text


def brief(text: str = "a to-do list") -> Brief:
    return Brief(kind="app", title="Tally", brief=text)


async def test_an_app_is_built_end_to_end() -> None:
    model = FakeAppModel(DESIGNED, [APP])
    updates = [u async for u in AppKind(model, check=False).build(brief())]  # type: ignore[arg-type]

    finished = updates[-1].built
    assert finished.html.count('data-pelita="store"') == 1
    assert app_id_of(finished.html)
    assert finished.spec.movement == "soft paper planner"
    assert "Keep today's tasks" in finished.summary
    assert "on the person's account" in finished.summary


async def test_the_design_reaches_the_writing_call() -> None:
    model = FakeAppModel(DESIGNED, [APP])
    [u async for u in AppKind(model, check=False).build(brief())]  # type: ignore[arg-type]
    assert "undo a clear" in model.systems[1]
    assert "a ticked task strikes through" in model.systems[1]


async def test_what_you_can_do_in_it_is_announced_first() -> None:
    model = FakeAppModel(DESIGNED, [APP])
    updates = [u async for u in AppKind(model, check=False).build(brief())]  # type: ignore[arg-type]
    planned = next(u for u in updates if type(u).__name__ == "Plan")
    assert planned.titles[0] == "add a task"


async def test_an_app_that_never_arrives_is_refused_not_stored() -> None:
    model = FakeAppModel(DESIGNED, [""])
    with pytest.raises(Exception, match="could not be written|returned nothing"):
        [u async for u in AppKind(model, check=False).build(brief())]  # type: ignore[arg-type]


async def test_a_change_keeps_the_apps_id() -> None:
    from app.artifacts.base import DesignSpec

    original = instrument(APP, "a1b2c3d4e5f6")
    model = FakeAppModel(APP.replace("Tally", "Tally Pro"), [])
    kind_ = AppKind(model, check=False)  # type: ignore[arg-type]
    model._replies = [APP.replace("<h1>Tally</h1>", "<h1>Tally Pro</h1>")]
    updates = [
        u
        async for u in kind_.revise(
            html=original, spec=DesignSpec(movement="x"), instruction="rename it"
        )
    ]
    changed = updates[-1].built.html
    assert "Tally Pro" in changed
    assert app_id_of(changed) == "a1b2c3d4e5f6"


# --- what an app keeps, through the API --------------------------------------


@pytest.fixture
def api(session):
    from app.api.deps import get_session, limit_auth
    from app.main import create_app

    app = create_app()

    async def _session():
        yield session

    async def _no_auth_limit() -> None:
        return None

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[limit_auth] = _no_auth_limit
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def made(session, db_user):
    conversation = Conversation(user_id=db_user.id, title="Apps")
    session.add(conversation)
    await session.flush()
    return await SqlArtifactRepository(session).create(
        conversation_id=conversation.id,
        user_id=db_user.id,
        message_id=None,
        kind="app",
        title="Tally",
        html=instrument(APP),
        design_spec={"movement": "soft paper planner", "width": 1280, "height": 800},
    )


async def _signed_in(client, username: str = "tester") -> None:
    response = await client.post(
        "/api/auth/signin", json={"identifier": username, "password": "hunter2hunter2"}
    )
    assert response.status_code == 200, response.text


async def test_an_app_starts_with_nothing_saved(api, made) -> None:
    async with api as client:
        await _signed_in(client)
        response = await client.get(f"/api/artifacts/{made.id}/state")
    assert response.status_code == 200
    assert response.json() == {"data": None}


async def test_what_an_app_saves_comes_back(api, made) -> None:
    saved = {"tasks": ["Finish the report", "Call Aina"], "filter": "all"}
    async with api as client:
        await _signed_in(client)
        put = await client.put(f"/api/artifacts/{made.id}/state", json={"data": saved})
        again = await client.put(
            f"/api/artifacts/{made.id}/state", json={"data": {**saved, "filter": "done"}}
        )
        got = await client.get(f"/api/artifacts/{made.id}/state")
    assert put.status_code == 204 and again.status_code == 204
    # Overwritten, not appended: this is where the app is now.
    assert got.json() == {"data": {**saved, "filter": "done"}}


async def test_starting_over_clears_it(api, made) -> None:
    async with api as client:
        await _signed_in(client)
        await client.put(f"/api/artifacts/{made.id}/state", json={"data": {"tasks": ["x"]}})
        cleared = await client.delete(f"/api/artifacts/{made.id}/state")
        got = await client.get(f"/api/artifacts/{made.id}/state")
    assert cleared.status_code == 204
    assert got.json() == {"data": None}


async def test_an_app_cannot_keep_a_database(api, made) -> None:
    huge = {"rows": ["x" * 1000] * 400}
    async with api as client:
        await _signed_in(client)
        response = await client.put(f"/api/artifacts/{made.id}/state", json={"data": huge})
    assert response.status_code == 422
    assert "limit" in response.json()["error"]["message"]


async def test_nobody_else_can_read_or_write_what_it_keeps(api, made, session) -> None:
    from app.core.security import hash_password
    from app.db.models.user import User

    session.add(
        User(
            username="intruder",
            email="intruder@example.com",
            password_hash=hash_password("hunter2hunter2"),
            display_name="Intruder",
        )
    )
    await session.flush()
    async with api as client:
        await _signed_in(client, "intruder")
        read = await client.get(f"/api/artifacts/{made.id}/state")
        write = await client.put(f"/api/artifacts/{made.id}/state", json={"data": {"x": 1}})
    assert read.status_code == 404
    assert write.status_code == 404


async def test_what_it_keeps_goes_when_the_app_does(api, made, session) -> None:
    async with api as client:
        await _signed_in(client)
        await client.put(f"/api/artifacts/{made.id}/state", json={"data": {"tasks": ["x"]}})
    gone = made.id
    await session.delete(made)
    await session.flush()
    from sqlalchemy import func, select

    from app.db.models.artifact_state import ArtifactState

    # Only this app's rows: the database is shared with whatever else has run.
    left = await session.scalar(
        select(func.count()).select_from(ArtifactState).where(ArtifactState.artifact_id == gone)
    )
    assert left == 0


# --- in a real browser --------------------------------------------------------


@pytest.fixture(autouse=True)
async def _no_browser_left_behind():
    """Each test runs on its own event loop, and the shared browser belongs to
    whichever loop started it."""
    yield
    from app.artifacts.raster import shutdown

    await shutdown()


async def _browser():
    pytest.importorskip("playwright")
    from app.artifacts.raster import RasterUnavailable, _ensure_browser

    try:
        return await _ensure_browser()
    except RasterUnavailable:
        pytest.skip("no browser in this environment")


async def test_saved_data_is_there_when_the_app_opens_and_saves_go_to_the_panel() -> None:
    """The whole round trip, framed the way the panel frames it: what was saved
    comes in with the document, and what changes goes out by message."""
    browser = await _browser()
    context = await browser.new_context()
    page = await context.new_page()
    framed = with_state(instrument(APP), {"tasks": ["Water the plants"]})
    host = (
        "<html><body><iframe sandbox='allow-scripts allow-forms' id='f'></iframe><script>"
        "window.said = [];"
        "window.addEventListener('message', (e) => {"
        "  if (e.data && e.data.source === 'pelita-store') window.said.push(e.data.data);"
        "});"
        f"document.getElementById('f').srcdoc = {json.dumps(framed).replace('</', '<\\/')};"
        "</script></body></html>"
    )
    try:
        await page.set_content(host)
        frame = page.frame_locator("#f")
        await frame.locator("#list li").first.wait_for(timeout=3000)
        assert await frame.locator("#list li").all_inner_texts() == ["Water the plants"]

        await frame.locator("#task").fill("Call Aina")
        await frame.locator("button[type=submit]").click()
        await page.wait_for_function("window.said.length > 0", timeout=3000)
        said = json.loads((await page.evaluate("window.said"))[-1])
        assert said == {"tasks": ["Water the plants", "Call Aina"]}
    finally:
        await context.close()


async def test_a_button_that_throws_is_found_by_using_the_app() -> None:
    from app.artifacts.apptest import use_app

    broken = APP.replace(
        "state.tasks = []; PelitaStore.save(state); render();",
        "state.tasks = done.filter(Boolean); render();",
    )
    await _browser()
    result = await use_app(instrument(broken))
    assert any("done is not defined" in e for e in result.errors), result


async def test_a_dialog_is_found_by_using_the_app() -> None:
    from app.artifacts.apptest import use_app

    asks = APP.replace(
        "state.tasks = []; PelitaStore.save(state); render();",
        "if (confirm('Clear?')) { state.tasks = []; render(); }",
    )
    await _browser()
    result = await use_app(instrument(asks))
    assert result.dialogs == ("confirm",)


async def test_a_working_app_is_used_without_complaint() -> None:
    from app.artifacts.apptest import use_app

    await _browser()
    result = await use_app(instrument(APP))
    assert result.ok, result


# --- an app cut off before its end -------------------------------------------


CUT_OFF = APP[: APP.index("render();\n</script>")]


async def test_an_app_cut_off_mid_script_is_written_again() -> None:
    """Near the size budget an app can run out of room before `</html>`. It
    ends mid-script and does nothing; it is written again, tighter."""
    model = FakeAppModel(DESIGNED, [CUT_OFF, APP])
    updates = [u async for u in AppKind(model, check=False).build(brief())]  # type: ignore[arg-type]

    assert updates[-1].built.html.rstrip().endswith("</html>")
    assert any(getattr(u, "label", "") == "Writing it again, tighter" for u in updates)


async def test_an_app_that_never_finishes_is_refused_not_stored() -> None:
    model = FakeAppModel(DESIGNED, [CUT_OFF, CUT_OFF])
    with pytest.raises(Exception, match="too large to finish"):
        [u async for u in AppKind(model, check=False).build(brief())]  # type: ignore[arg-type]


async def test_a_change_cut_off_mid_script_leaves_the_app_as_it_was() -> None:
    from app.artifacts.base import DesignSpec

    model = FakeAppModel(CUT_OFF, [])
    with pytest.raises(Exception, match="unfinished"):
        [
            u
            async for u in AppKind(model, check=False).revise(  # type: ignore[arg-type]
                html=instrument(APP), spec=DesignSpec(movement="x"), instruction="add tags"
            )
        ]
