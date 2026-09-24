"""Planning, assembling, routing and checking a website.

Most of this runs without a model or a browser: the plan is read from JSON,
the site is assembled from strings, and the routing is text in a document.
The last section opens real sites in the same Chromium the builds use, because
routing and forms are behaviour, and behaviour is only proved by running it.
"""

from __future__ import annotations

import pytest

from app.artifacts.base import Brief
from app.artifacts.imagery import detach_named, reattach_named
from app.artifacts.site_assembly import (
    NAV_MARK,
    PAGES_MARK,
    Link,
    assemble,
    dead_links,
    mend_links,
    normalise_page,
    page_spans,
    pages_of,
    place_nav,
    route,
    scrub_invented_images,
    shell_of,
    show_photos,
    strip_ours,
)
from app.artifacts.sitetest import SiteCheck, Wide
from app.artifacts.website import Site, WebsiteKind, _ensure_marks, _with_photos
from app.artifacts.website_plan import SitePlan, read_plan, wanted_pages
from app.artifacts.website_prompts import MAX_PAGES

SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kopi Lane</title>
<style>
/* .container .section .btn */
:root { --ground: #f6f1e9; --ink: #1d1a16; }
body { margin: 0; font-family: sans-serif; background: var(--ground); color: var(--ink); }
.container { max-width: 1100px; margin: 0 auto; padding: 0 20px; }
.section { padding: 48px 0; }
.nav-link[aria-current="page"] { font-weight: 700; }
</style>
</head>
<body>
<header class="site-header"><a href="#/home">Kopi Lane</a>
<nav class="site-nav"><!--NAV--></nav></header>
<main id="site"><!--PAGES--></main>
<footer class="site-footer"><p>Kopi Lane, Ipoh</p><!--NAV--></footer>
<script>document.querySelector('.site-header').classList.add('ready');</script>
</body>
</html>"""


def page(slug: str, words: str = "", extra: str = "") -> str:
    text = words or (
        f"This is the {slug} page of Kopi Lane, a small coffee shop on a quiet lane "
        "in old town Ipoh that roasts its own beans every morning at six."
    )
    return (
        f'<section data-page="{slug}" aria-label="{slug}">'
        f'<section class="section" id="{slug}-hero"><div class="container">'
        f"<h1>{slug.title()}</h1><p>{text}</p>{extra}</div></section></section>"
    )


LINKS = [Link("Home", "#/home"), Link("Menu", "#/menu"), Link("Visit", "#/visit")]
SLUGS = ["home", "menu", "visit"]
TITLES = {"home": "Home", "menu": "Menu", "visit": "Visit"}


def site_document(pages: list[str] | None = None, shell: str = SHELL) -> str:
    return assemble(
        shell,
        pages or [normalise_page(page(s), s, TITLES[s]) for s in SLUGS],
        links=LINKS,
        slugs=SLUGS,
        titles=TITLES,
        site="Kopi Lane",
    )


# --- how many pages -----------------------------------------------------------


def brief(text: str = "", *, count: int = 0, title: str = "A site") -> Brief:
    return Brief(kind="website", title=title, brief=text, count=count)


def test_the_number_the_person_gave_wins() -> None:
    assert wanted_pages(brief("a cafe", count=4)) == 4


def test_a_number_in_the_brief_is_the_fallback() -> None:
    assert wanted_pages(brief("a 3 page website for my clinic")) == 3
    assert wanted_pages(brief("five pages")) == 0  # words are not numbers


def test_nothing_said_means_the_plan_decides() -> None:
    """A landing page is one page and a restaurant is several; a fixed default
    would be wrong for one of them every time."""
    assert wanted_pages(brief("a landing page for my app")) == 0


def test_a_silly_number_is_brought_back_into_range() -> None:
    assert wanted_pages(brief("x", count=99)) == MAX_PAGES


# --- reading the plan ---------------------------------------------------------


PLANNED = {
    "name": "Kopi Lane",
    "tagline": "Roasted at six, poured all day",
    "movement": "warm hand-made",
    "rationale": "A lane-side roaster should feel like paper bags and chalk.",
    "palette": ["#f6f1e9", "#1d1a16", "#c2410c", "not a colour", "#2f5d50"],
    "display_font": "Fraunces",
    "body_font": "Work Sans",
    "pages": [
        {
            "slug": "index",
            "title": "Home",
            "nav": "Home",
            "sections": [{"id": "hero", "job": "the promise"}],
        },
        {
            "slug": "Our Menu!",
            "title": "Menu",
            "nav": "Menu",
            "sections": [{"id": "hero", "job": "the menu hero"}],
        },
        {"slug": "menu", "title": "Menu again", "nav": "More"},
    ],
    "image_queries": ["pour-over coffee on a wooden counter", "", "old town Ipoh shophouse"],
}


def test_the_first_page_is_always_home() -> None:
    """Every link with nowhere else to go ends up there, so it has a known name."""
    assert read_plan(PLANNED, "x").pages[0].slug == "home"


def test_slugs_are_safe_and_unique() -> None:
    slugs = read_plan(PLANNED, "x").slugs
    assert slugs == ["home", "our-menu", "menu"]


def test_section_ids_are_unique_across_the_whole_site() -> None:
    """Every page is in one document. Two sections called "hero" and the
    second page's anchor links scroll to the first page's hero."""
    plan = read_plan(PLANNED, "x")
    ids = [s.id for p in plan.pages for s in p.sections]
    assert len(ids) == len(set(ids))
    assert ids[0] == "hero"


def test_a_colour_that_is_not_a_colour_is_dropped() -> None:
    assert "not a colour" not in read_plan(PLANNED, "x").palette


def test_empty_photo_queries_are_dropped() -> None:
    assert read_plan(PLANNED, "x").image_queries == (
        "pour-over coffee on a wooden counter",
        "old town Ipoh shophouse",
    )


def test_a_plan_with_nothing_in_it_has_no_pages() -> None:
    assert read_plan({}, "A site").pages == ()


def test_a_several_page_site_links_to_pages() -> None:
    assert read_plan(PLANNED, "x").links[1] == Link("Menu", "#/our-menu")


def test_a_one_page_site_links_to_its_sections() -> None:
    plan = read_plan(
        {
            "pages": [
                {
                    "slug": "home",
                    "title": "Home",
                    "sections": [
                        {"id": "hero", "job": "x"},
                        {"id": "features", "job": "x", "nav": "Features"},
                        {"id": "pricing", "job": "x", "nav": "Pricing"},
                    ],
                }
            ]
        },
        "An app",
    )
    assert plan.links == [Link("Features", "#features"), Link("Pricing", "#pricing")]


def test_a_one_page_site_that_named_nothing_still_has_a_nav() -> None:
    plan = SitePlan(
        name="x",
        pages=read_plan(
            {"pages": [{"slug": "home", "sections": [{"id": "hero"}, {"id": "how-it-works"}]}]}, "x"
        ).pages,
    )
    assert plan.links == [Link("How it works", "#how-it-works")]


# --- the nav ------------------------------------------------------------------


def test_the_nav_goes_everywhere_the_shell_asked_for_it() -> None:
    placed = place_nav(SHELL, LINKS)
    assert NAV_MARK not in placed
    assert placed.count('href="#/menu"') == 2  # header and footer


def test_a_shell_that_forgot_the_marker_still_gets_a_nav() -> None:
    forgot = SHELL.replace("<!--NAV-->", "")
    assert 'href="#/visit"' in place_nav(forgot, LINKS)


def test_the_nav_can_be_taken_back_out() -> None:
    placed = place_nav(SHELL, LINKS)
    assert shell_of(placed).count(NAV_MARK) == 2


def test_labels_are_escaped() -> None:
    placed = place_nav(SHELL, [Link('<img src=x onerror="alert(1)">', "#/home")])
    assert "<img src=x" not in placed


# --- the pages ----------------------------------------------------------------


def test_a_page_is_found_by_depth_not_by_its_first_closing_tag() -> None:
    document = site_document()
    spans = page_spans(document)
    assert [slug for slug, _, _ in spans] == SLUGS
    home = document[spans[0][1] : spans[0][2]]
    assert home.count("<section") == home.count("</section")


def test_the_shell_comes_back_without_its_pages() -> None:
    shell = shell_of(site_document())
    assert PAGES_MARK in shell
    assert 'data-page="menu"' not in shell
    assert "data-pelita" not in shell


def test_a_page_keeps_the_plans_slug_whatever_it_wrote() -> None:
    """The nav and the router were built from the plan; a writer that renamed
    its own page would have made it unreachable."""
    written = '<section data-page="our-menu-page" class="menu"><h1>Menu</h1></section>'
    element = normalise_page(written, "menu", "Menu")
    assert element.startswith(
        '<section data-page="menu" data-title="Menu" aria-label="Menu" class="menu">'
    )


def test_prose_and_fences_around_a_page_are_dropped() -> None:
    written = 'Here is your page:\n```html\n<section data-page="menu"><h1>Menu</h1></section>\n```'
    element = normalise_page(written, "menu", "Menu")
    assert element.startswith("<section data-page")
    assert "Here is your page" not in element


def test_a_page_with_no_wrapper_is_wrapped() -> None:
    written = (
        '<section class="section" id="hero"><h1>Hi</h1></section>'
        '<section class="section"><p>Two</p></section>'
    )
    element = normalise_page(written, "menu", "Menu")
    assert pages_of(element)[0][0] == "menu"
    assert "<p>Two</p>" in element


def test_a_page_cannot_carry_a_script_or_a_handler() -> None:
    """Behaviour belongs to the shell. A page that could run code is a second,
    unreviewed place for it to go wrong."""
    written = (
        '<section data-page="menu"><script>alert(1)</script>'
        '<button onclick="steal()" class="btn">Go</button></section>'
    )
    element = normalise_page(written, "menu", "Menu")
    assert "<script" not in element
    assert "onclick" not in element
    assert 'class="btn"' in element


def test_invented_pictures_are_taken_out() -> None:
    written = (
        '<img src="https://images.unsplash.com/photo-123" alt="coffee">'
        '<div style="background: url(https://picsum.photos/800)"></div>'
        '<div style="background-image: var(--photo)"></div>'
    )
    scrubbed = scrub_invented_images(written)
    assert "unsplash" not in scrubbed
    assert "picsum" not in scrubbed
    assert "var(--photo)" in scrubbed


def test_a_photograph_passed_through_a_convention_of_its_own_still_shows() -> None:
    """The real one: the shell's `.media` showed `var(--img)` only with a
    `data-img` attribute, and the page set `--img: var(--photo-2)` without
    it. Every value right, and the hero an empty brown box."""
    written = '<div class="hero-media media" role="img" style="--img: var(--photo-2);"></div>'
    shown = show_photos(written)
    assert "background-image: var(--photo-2)" in shown
    assert "--img: var(--photo-2)" in shown


def test_a_photograph_already_set_as_a_background_is_left_alone() -> None:
    written = '<div style="background: center / cover var(--photo-3)"></div>'
    assert show_photos(written) == written


def test_pages_are_normalised_with_their_photographs_showing() -> None:
    element = normalise_page(
        '<section data-page="home"><div class="media" style="--img: var(--photo)"></div></section>',
        "home",
        "Home",
    )
    assert "background-image: var(--photo)" in element


def test_a_shell_that_wrote_a_page_anyway_gets_its_marker_back() -> None:
    wrote = SHELL.replace("<!--PAGES-->", page("home"))
    assert PAGES_MARK in _ensure_marks(wrote)
    assert 'data-page="home"' not in _ensure_marks(wrote)


def test_a_shell_with_no_marker_gets_one_in_main() -> None:
    missing = SHELL.replace("<!--PAGES-->", "<p>placeholder</p>")
    assert '<main id="site"><!--PAGES--></main>' in _ensure_marks(missing)


# --- links --------------------------------------------------------------------


def test_a_link_to_a_page_with_a_near_name_goes_there() -> None:
    mended = mend_links('<a href="#/visits">Find us</a>', SLUGS)
    assert 'href="#/visit"' in mended


def test_a_link_to_a_page_nobody_planned_goes_home() -> None:
    mended = mend_links('<a href="#/checkout">Buy</a>', SLUGS)
    assert 'href="#/home"' in mended


def test_an_assembled_site_has_no_dead_links() -> None:
    pages = [page("home", extra='<a href="#/contact-us">Contact</a>'), page("menu"), page("visit")]
    assert dead_links(site_document(pages), SLUGS) == []


# --- routing ------------------------------------------------------------------


def test_the_first_page_is_decided_before_anything_is_painted() -> None:
    """Otherwise every page shows for a moment, stacked, before the script at
    the end of the body gets round to hiding them."""
    document = site_document()
    head = document.index("<head>")
    guard = document.index('data-pelita="route-head"')
    assert guard - head < 20
    assert guard < document.index("<meta")


def test_the_router_comes_after_the_design_and_its_script() -> None:
    document = site_document()
    assert document.index('data-pelita="router"') > document.index("classList.add('ready')")
    assert document.index('data-pelita="site"') > document.index("--ground")


def test_routing_is_added_once_however_many_times_a_site_is_changed() -> None:
    document = site_document()
    again = route(document, slugs=SLUGS, titles=TITLES, site="Kopi Lane")
    assert again.count('data-pelita="router"') == 1
    assert again.count('data-pelita="route-head"') == 1
    assert again.count('data-pelita="site"') == 1


def test_a_title_cannot_end_the_router_early() -> None:
    document = route(SHELL, slugs=["home"], titles={"home": "</script><b>"}, site="x")
    router = document[document.index('data-pelita="router"') :]
    assert router.index("</script>") > router.index("TITLES")
    assert "\\u003c/script>" in router


def test_the_design_is_untouched_by_routing() -> None:
    assert strip_ours(site_document()).count("--ground: #f6f1e9") == 1


# --- a site, taken apart and put back -----------------------------------------


def test_a_stored_site_reads_back_into_the_same_parts() -> None:
    site = Site.read(site_document())
    assert site.slugs == SLUGS
    assert site.titles["menu"] == "Menu"
    assert site.links == tuple(LINKS)
    assert site.name == "Kopi Lane"


def test_a_site_read_back_assembles_into_the_same_document() -> None:
    document = site_document()
    assert Site.read(document).document() == document


def test_one_page_is_replaced_and_nothing_else_moves() -> None:
    site = Site.read(site_document())
    changed = site.with_page(
        "menu", normalise_page(page("menu", "Nasi lemak, kopi, kaya toast."), "menu", "Menu")
    )
    assert "kaya toast" in changed.document()
    assert dict(changed.pages)["home"] == dict(site.pages)["home"]


# --- pictures -----------------------------------------------------------------


def test_a_picture_nobody_used_stays_out_and_the_others_keep_their_names() -> None:
    document = site_document(
        [
            page(
                "home", extra='<div class="media" style="background-image: var(--photo-3)"></div>'
            ),
            page("menu"),
            page("visit"),
        ]
    )
    photos = {"--photo": "data:image/jpeg;base64,AAA", "--photo-3": "data:image/jpeg;base64,CCC"}
    with_photos = _with_photos(document, photos)
    assert "CCC" in with_photos
    assert "AAA" not in with_photos
    assert '--photo-3: url("data:image/jpeg;base64,CCC")' in with_photos


def test_pictures_come_back_out_under_their_own_names() -> None:
    """Put back in order, `--photo-3` became `--photo-2`, and whatever asked
    for the third picture was left with nothing."""
    document = reattach_named(SHELL, {"--photo": "data:a", "--photo-3": "data:c"})
    plain, named = detach_named(document)
    assert named == {"--photo": "data:a", "--photo-3": "data:c"}
    assert "data:c" not in plain
    assert '--photo-3: url("data:c")' in reattach_named(plain, named)


# --- what the browser found ----------------------------------------------------


def test_a_clean_site_has_nothing_to_fix() -> None:
    assert SiteCheck().ok
    assert SiteCheck().pages_to_fix() == []


def test_script_errors_are_the_shells_because_pages_have_no_scripts() -> None:
    result = SiteCheck(errors=("menu is not defined",))
    assert any("menu is not defined" in c for c in result.shell_complaints())
    assert result.pages_to_fix() == []


def test_something_too_wide_goes_to_the_page_it_is_on() -> None:
    result = SiteCheck(wide=(Wide(page="menu", what="table.prices", by=420),))
    assert result.pages_to_fix() == ["menu"]
    assert "420px" in result.page_complaints("menu")[0]
    assert result.shell_complaints() == []


def test_something_too_wide_in_the_header_goes_to_the_shell() -> None:
    result = SiteCheck(wide=(Wide(page="", what="nav.site-nav", by=90),))
    assert "header or footer" in result.shell_complaints()[0]
    assert result.pages_to_fix() == []


def test_an_empty_page_is_a_page_to_fix() -> None:
    assert SiteCheck(empty=("visit",)).pages_to_fix() == ["visit"]


# --- the kind -----------------------------------------------------------------


def test_a_website_may_run_scripts_and_answer_its_own_forms() -> None:
    assert WebsiteKind.sandbox.iframe_sandbox == "allow-scripts allow-forms"


def test_a_website_never_gets_the_origin_it_was_framed_from() -> None:
    assert "allow-same-origin" not in WebsiteKind.sandbox.iframe_sandbox
    assert "allow-same-origin" not in WebsiteKind.sandbox.csp


def test_a_form_still_cannot_send_anything_anywhere() -> None:
    """`allow-forms` lets the submit event fire; it does not let a form send."""
    assert "form-action 'none'" in WebsiteKind.sandbox.csp
    assert "connect-src 'none'" in WebsiteKind.sandbox.csp


def test_the_other_kinds_did_not_gain_forms() -> None:
    from app.artifacts.games import GamesKind
    from app.artifacts.poster import PosterKind

    assert GamesKind.sandbox.iframe_sandbox == "allow-scripts"
    assert PosterKind.sandbox.iframe_sandbox == ""


def test_the_website_kind_is_registered() -> None:
    from app.artifacts.registry import build_kinds
    from app.core.config import Settings

    kinds = build_kinds(Settings(_env_file=None, artifact_model="m", llm_api_key="k"))  # type: ignore[call-arg]
    assert "website" in kinds


# --- the whole build, against a fake model -----------------------------------


class FakeSiteModel:
    """Answers the plan, the shell, then each page, then any repairs."""

    name = "fake-artifact"

    def __init__(self, plan: dict, shell: str, pages: dict[str, str]) -> None:
        self._plan = plan
        self._shell = shell
        self._pages = pages
        self.systems: list[str] = []
        self.requests: list[str] = []

    async def decide(self, system, user, *, max_tokens=1600):
        self.systems.append(system)
        self.requests.append(user)
        return self._plan

    async def write(self, system, user, into, *, temperature=None):
        self.systems.append(system)
        self.requests.append(user)
        if "shell of a website" in system:
            into.text = self._shell
        else:
            slug = next(s for s in self._pages if f'data-page="{s}"' in system)
            into.text = self._pages[slug]
        yield into.text


PLAN = {
    "name": "Kopi Lane",
    "movement": "warm hand-made",
    "rationale": "Paper bags and chalk.",
    "palette": ["#f6f1e9", "#1d1a16", "#c2410c"],
    "display_font": "Fraunces",
    "body_font": "Work Sans",
    "pages": [
        {
            "slug": "home",
            "title": "Home",
            "nav": "Home",
            "sections": [{"id": "hero", "job": "the promise"}],
        },
        {
            "slug": "menu",
            "title": "Menu",
            "nav": "Menu",
            "sections": [{"id": "drinks", "job": "prices"}],
        },
        {
            "slug": "visit",
            "title": "Visit",
            "nav": "Visit",
            "sections": [{"id": "where", "job": "address"}],
        },
    ],
}


async def build(model: FakeSiteModel) -> list:
    kind = WebsiteKind(model, check=False)  # type: ignore[arg-type]
    return [u async for u in kind.build(brief("a website for my cafe", title="Kopi Lane"))]


async def test_a_site_is_built_end_to_end() -> None:
    model = FakeSiteModel(PLAN, SHELL, {s: page(s) for s in SLUGS})
    updates = await build(model)

    finished = updates[-1].built
    assert [slug for slug, _ in pages_of(finished.html)] == SLUGS
    assert finished.html.count('data-pelita="router"') == 1
    assert 'href="#/visit"' in finished.html
    assert finished.spec.width == 1280


async def test_the_look_and_the_pages_are_announced_before_anything_is_written() -> None:
    model = FakeSiteModel(PLAN, SHELL, {s: page(s) for s in SLUGS})
    updates = await build(model)
    names = [type(u).__name__ for u in updates]

    assert names.index("Designed") < names.index("Chunk")
    planned = next(u for u in updates if type(u).__name__ == "Plan")
    assert planned.titles == ("Home", "Menu", "Visit")


async def test_each_page_arrives_in_order_as_something_to_look_at() -> None:
    model = FakeSiteModel(PLAN, SHELL, {s: page(s) for s in SLUGS})
    parts = [u for u in await build(model) if type(u).__name__ == "Part"]

    assert [p.title for p in parts] == ["Home", "Menu", "Visit"]
    assert all("data-page=" in p.html and "data-pelita" not in p.html for p in parts)
    # Shown in a frame that runs no scripts: one left in is a console error each.
    assert all("<script" not in p.html for p in parts)


async def test_every_page_is_written_against_the_shells_stylesheet() -> None:
    model = FakeSiteModel(PLAN, SHELL, {s: page(s) for s in SLUGS})
    await build(model)

    pages = [s for s in model.systems if "one page of a website" in s]
    assert len(pages) == 3
    assert all("--ground: #f6f1e9" in s for s in pages)


async def test_a_page_that_cannot_be_written_leaves_the_menu_with_it() -> None:
    """A site one page short is still a site; a site with a dead page in its
    menu is broken."""

    class Refuses(FakeSiteModel):
        async def write(self, system, user, into, *, temperature=None):
            if 'data-page="visit"' in system:
                from app.artifacts.base import ArtifactUnavailable

                raise ArtifactUnavailable("no")
                yield ""  # pragma: no cover
            async for piece in super().write(system, user, into, temperature=temperature):
                yield piece

    model = Refuses(PLAN, SHELL, {s: page(s) for s in SLUGS})
    finished = (await build(model))[-1].built

    assert [slug for slug, _ in pages_of(finished.html)] == ["home", "menu"]
    assert 'class="nav-link" href="#/visit"' not in finished.html


# --- in a real browser --------------------------------------------------------


@pytest.fixture(autouse=True)
async def _no_browser_left_behind():
    """Each test runs on an event loop of its own, and the shared browser
    belongs to whichever loop started it. Left running, the next test awaits a
    browser on a loop that has already closed, and waits for ever."""
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


async def _opened(html: str, width: int = 1280, height: int = 800):
    browser = await _browser()
    context = await browser.new_context(viewport={"width": width, "height": height})
    page_ = await context.new_page()
    await page_.set_content(html, wait_until="load")
    await page_.wait_for_timeout(200)
    return context, page_


_SHOWN = """() => Array.from(document.querySelectorAll('[data-page]'))
  .filter((p) => p.getBoundingClientRect().height > 0)
  .map((p) => p.getAttribute('data-page'))"""


async def test_only_one_page_shows_and_the_menu_moves_between_them() -> None:
    context, tab = await _opened(site_document())
    try:
        assert await tab.evaluate(_SHOWN) == ["home"]

        await tab.click('header a.nav-link[href="#/menu"]')
        await tab.wait_for_timeout(100)
        assert await tab.evaluate(_SHOWN) == ["menu"]
        current = await tab.get_attribute('header a.nav-link[href="#/menu"]', "aria-current")
        assert current == "page"

        await tab.evaluate("() => { location.hash = '#/visit'; }")
        await tab.wait_for_timeout(100)
        assert await tab.evaluate(_SHOWN) == ["visit"]
    finally:
        await context.close()


async def test_the_address_opens_the_page_it_names() -> None:
    """A downloaded site opened as `site.html#/visit` starts on Visit."""
    context, tab = await _opened(
        site_document().replace(
            '<script data-pelita="route-head">',
            "<script>history.replaceState(null, '', '#/visit');</script>"
            '<script data-pelita="route-head">',
        )
    )
    try:
        assert await tab.evaluate(_SHOWN) == ["visit"]
    finally:
        await context.close()


async def test_a_form_answers_itself_and_sends_nothing() -> None:
    form = (
        '<form data-form><label>Name <input name="n" required></label>'
        '<button type="submit">Send</button>'
        '<p class="form-success" hidden>Thanks, we will call you back.</p></form>'
    )
    context, tab = await _opened(
        site_document([page("home", extra=form), page("menu"), page("visit")])
    )
    try:
        sent: list[str] = []
        tab.on("request", lambda r: sent.append(r.url))

        await tab.click('button[type="submit"]')
        assert not await tab.is_visible(".form-success")  # required field is empty

        await tab.fill('input[name="n"]', "Aina")
        await tab.click('button[type="submit"]')
        await tab.wait_for_timeout(100)
        assert await tab.is_visible(".form-success")
        assert not await tab.is_visible('input[name="n"]')
        assert sent == []
    finally:
        await context.close()


async def test_something_wider_than_a_phone_is_found_on_its_page() -> None:
    from app.artifacts.sitetest import check_site

    wide = '<div class="prices" style="width: 1100px">Kopi O 2.50 · Kopi C 3.00</div>'
    await _browser()
    result = await check_site(
        site_document([page("home"), page("menu", extra=wide), page("visit")]), SLUGS
    )

    assert result.pages_to_fix() == ["menu"]
    assert "div.prices" in result.wide[0].what
    assert result.errors == ()


async def test_a_grid_that_would_blow_out_on_a_phone_does_not() -> None:
    """The real one: a one-column grid whose track grew to its content's
    min-content width, 24px past a 390px screen. Grid and flex items refuse to
    shrink below their content unless told they may; the guard tells them, at
    zero specificity, so any rule the design wrote still wins."""
    from app.artifacts.sitetest import check_site

    blowout = (
        '<div style="display: grid; grid-template-columns: 1fr">'
        '<div class="stack"><h2 style="font-size: 40px">'
        "KopiLaneHeritageRoasteryOfJalanPanglima</h2></div></div>"
    )
    await _browser()
    guarded = site_document([page("home", extra=blowout), page("menu"), page("visit")])
    assert (await check_site(guarded, SLUGS)).wide == ()

    # And the same page without the guard is exactly the failure it prevents.
    bare = guarded.replace(":where([data-page] *, .site-footer *) { min-width: 0; }", "")
    bare = bare.replace(":where([data-page], .site-footer) { overflow-wrap: break-word; }", "")
    assert (await check_site(bare, SLUGS)).pages_to_fix() == ["home"]


async def test_a_strip_that_scrolls_inside_its_own_box_is_not_too_wide() -> None:
    from app.artifacts.sitetest import check_site

    strip = (
        '<div style="overflow-x: auto; max-width: 100%">'
        '<div style="width: 1400px">a gallery that scrolls sideways on purpose</div></div>'
    )
    await _browser()
    result = await check_site(
        site_document([page("home", extra=strip), page("menu"), page("visit")]), SLUGS
    )

    assert result.wide == ()


async def test_a_clean_site_opens_clean() -> None:
    from app.artifacts.sitetest import check_site

    await _browser()
    result = await check_site(site_document(), SLUGS)
    assert result.ok, result


async def test_an_empty_page_and_a_script_error_are_both_found() -> None:
    from app.artifacts.sitetest import check_site

    broken = SHELL.replace(
        "document.querySelector('.site-header').classList.add('ready');",
        "document.querySelector('.menu-toggle').addEventListener('click', open);",
    )
    await _browser()
    result = await check_site(
        site_document(
            [page("home"), page("menu"), '<section data-page="visit"><h1>Visit</h1></section>'],
            shell=broken,
        ),
        SLUGS,
    )

    assert result.empty == ("visit",)
    assert result.errors


# --- changing a site from the chat ------------------------------------------


class FakeChanger:
    """Answers the one decision a change needs, and writes any new page."""

    name = "fake-artifact"

    def __init__(self, decision: dict, page_html: str = "") -> None:
        self._decision = decision
        self._page = page_html
        self.asked: list[str] = []

    async def decide(self, system, user, *, max_tokens=1600):
        self.asked.append(user)
        return self._decision

    async def write(self, system, user, into, *, temperature=None):
        into.text = self._page
        yield into.text


async def revised(decision: dict, page_html: str = "", html: str | None = None):
    model = FakeChanger(decision, page_html)
    kind = WebsiteKind(model, check=False)  # type: ignore[arg-type]
    from app.artifacts.base import DesignSpec

    updates = [
        u
        async for u in kind.revise(
            html=html or site_document(), spec=DesignSpec(movement="x"), instruction="change it"
        )
    ]
    return updates[-1].built.html, model


def distinct_site() -> str:
    return site_document(
        [
            normalise_page(
                page("home", "Kopi Lane has roasted on this lane since 1952, every day."),
                "home",
                "Home",
            ),
            normalise_page(
                page("menu", "Kopi O, kopi C, and a pour-over of the morning's batch."),
                "menu",
                "Menu",
            ),
            normalise_page(
                page("visit", "Twelve Jalan Panglima, open eight until six, shut Mondays."),
                "visit",
                "Visit",
            ),
        ]
    )


async def test_a_word_is_changed_and_nothing_else_is() -> None:
    before = distinct_site()
    after, _ = await revised(
        {
            "action": "edit",
            "edits": [
                {"find": "a pour-over of the morning's batch", "replace": "a pour-over at dawn"}
            ],
        },
        html=before,
    )
    assert "a pour-over at dawn" in after
    assert after.replace("a pour-over at dawn", "a pour-over of the morning's batch") == before
    assert after.count('data-pelita="router"') == 1


async def test_the_model_is_shown_the_site_without_the_router() -> None:
    """It is our code, the same on every site. Showing it invites an edit to it."""
    _, model = await revised(
        {"action": "edit", "edits": [{"find": "shut Mondays", "replace": "closed on Mondays"}]},
        html=distinct_site(),
    )
    assert "data-pelita" not in model.asked[0]


async def test_an_edit_that_matches_nothing_leaves_the_site_as_it_was() -> None:
    with pytest.raises(Exception, match="left as it was"):
        await revised(
            {"action": "edit", "edits": [{"find": "text that is nowhere at all", "replace": "x"}]}
        )


async def test_a_new_page_is_written_and_joins_the_menu() -> None:
    after, _ = await revised(
        {
            "action": "add_page",
            "slug": "events",
            "title": "Events",
            "nav": "Events",
            "after": "menu",
        },
        page_html=page("events"),
    )
    assert [slug for slug, _ in pages_of(after)] == ["home", "menu", "events", "visit"]
    nav = after[after.index("<!--pelita:nav-->") : after.index("<!--/pelita:nav-->")]
    assert nav.index("#/menu") < nav.index("#/events") < nav.index("#/visit")


async def test_a_page_is_removed_along_with_its_link() -> None:
    after, _ = await revised({"action": "remove_page", "slugs": ["visit"]})
    assert [slug for slug, _ in pages_of(after)] == ["home", "menu"]
    assert 'class="nav-link" href="#/visit"' not in after


async def test_the_home_page_cannot_be_removed() -> None:
    """Every link with nowhere else to go ends up there."""
    with pytest.raises(Exception, match="cannot lose|left as it was"):
        await revised({"action": "remove_page", "slugs": ["home"]})


async def test_a_change_keeps_every_photograph_under_its_own_name() -> None:
    with_photo = reattach_named(
        site_document(
            [
                page("home", extra='<div style="background-image: var(--photo-3)"></div>'),
                page("menu"),
                page("visit"),
            ]
        ),
        {"--photo-3": "data:image/jpeg;base64,CCC"},
    )
    after, model = await revised(
        {"action": "remove_page", "slugs": ["visit"]},
        html=with_photo,
    )
    assert '--photo-3: url("data:image/jpeg;base64,CCC")' in after
    assert "base64,CCC" not in model.asked[0]  # never sent to the model


# --- what the chat model is told ---------------------------------------------


def test_the_chat_model_is_told_what_the_site_actually_is() -> None:
    """Told only that something was made, it called a warm orange-on-ink page
    "a clean blue and white colour scheme" and a four-page site "single-page"."""
    from app.artifacts.base import Built, DesignSpec
    from app.services.chat_service import _facts

    built = Built(
        html="",
        spec=DesignSpec(
            movement="shophouse letterpress",
            rationale="a heritage roaster should feel like a handbill",
            display_font="DM Serif Display",
            body_font="Spectral",
        ),
        summary="a website of 4 pages: Home, Menu, Story, Visit",
    )
    said = _facts(built)
    assert "4 pages: Home, Menu, Story, Visit" in said
    assert "shophouse letterpress" in said
    assert "DM Serif Display and Spectral" in said
    assert "never name a colour" in said


def test_a_site_summarises_itself_by_its_pages() -> None:
    from app.artifacts.website import _summary

    assert _summary(Site.read(site_document())) == "a website of 3 pages: Home, Menu, Visit"
