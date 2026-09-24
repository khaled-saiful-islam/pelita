"""The website kind.

A website is the first artifact here that is several things at once: a design
system, a header and footer that frame every page, and the pages themselves.
It is built the way a studio would build one, in that order.

1. **A plan.** What it is for, who it is for, the direction, and exactly what
   is on each page -- decided before any of it is written, so every later step
   has something to be faithful to.
2. **The shell.** One stylesheet every page is built from, the header, the
   footer, and the little behaviour a site needs. Written while the
   photographs are being found, because neither needs the other.
3. **The pages**, several at a time, each against that stylesheet. They land
   in the panel as they are finished, so a four-page site is watched arriving
   rather than waited for.
4. **Opened in a browser**, on a desktop and a phone, every page visited. What
   is wrong is sent back to the part it belongs to -- the shell, or one page --
   rather than to a model asked to rewrite the whole site.

Routing, the nav's page links, scroll-reveal and the forms are not the model's
to write. They are the same on every site and the part that breaks when it is
improvised, so `site_assembly` adds them after, from code with tests.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field, replace
from html import unescape
from time import perf_counter
from typing import Any

from app.artifacts.base import (
    ArtifactUnavailable,
    Brief,
    BuildUpdate,
    Built,
    Canvas,
    Chunk,
    Designed,
    DesignSpec,
    Finished,
    Part,
    Plan,
    SandboxPolicy,
    Step,
)
from app.artifacts.edits import apply_edits, read_edits
from app.artifacts.imagery import (
    Photo,
    detach_named,
    find_photo,
    reattach_named,
    variable_for,
)
from app.artifacts.model import ArtifactModel, Written, strip_fence
from app.artifacts.raster import RasterUnavailable
from app.artifacts.site_assembly import (
    PAGES_MARK,
    Link,
    assemble,
    normalise_page,
    pages_of,
    place_nav,
    scrub_invented_images,
    shell_of,
    slugify,
    strip_ours,
)
from app.artifacts.sitetest import SiteCheck, check_site
from app.artifacts.website_plan import (
    Page,
    Section,
    SitePlan,
    change_context,
    context_of,
    described,
    fitted,
    fix_request,
    page_brief,
    photo_brief,
    photo_names,
    plan_brief,
    read_plan,
    shell_request,
    spec_of,
    still_there,
    survivable,
    unique,
    wanted_pages,
)
from app.artifacts.website_prompts import (
    DESIGN_SYSTEM,
    FIX_PAGE_SYSTEM,
    FIX_SHELL_SYSTEM,
    MAX_PHOTOS,
    MAX_SECTIONS,
    PAGE_SYSTEM,
    SHELL_SYSTEM,
    SITE_CHANGE_SYSTEM,
    SITE_HEIGHT,
    SITE_WIDTH,
)
from app.tools.serpapi import SearchProvider

logger = logging.getLogger(__name__)

DESKTOP = Canvas(width=SITE_WIDTH, height=SITE_HEIGHT, page=f"{SITE_WIDTH}px {SITE_HEIGHT}px")
# Pages written at once. Enough that a five-page site is not five minutes;
# few enough that one site does not take every slot the model has.
AT_ONCE = 3
# One round of repairs. Each part is repaired on its own, so the round is
# small; a second has not yet been the difference between a site that works
# and one that does not.
FIX_ATTEMPTS = 1
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")
_COUNT = re.compile(r"\b(\d{1,2})\s*[- ]?\s*pages?\b", re.IGNORECASE)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.S)
_STYLE = re.compile(r"<style\b(?![^>]*data-pelita)[^>]*>(.*?)</style>", re.IGNORECASE | re.S)
_NAV_LINK = re.compile(r'<a class="nav-link" href="([^"]*)">(.*?)</a>', re.S)
_NAV_REGION = re.compile(r"<!--pelita:nav-->(.*?)<!--/pelita:nav-->", re.S)
_SCRIPTS = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.S)
_ROLES = ("ground", "ink", "accent", "support", "deep", "quiet")
_FALLBACK_PALETTE = ("#f6f1e9", "#1d1a16", "#c2410c", "#2f5d50", "#0f1714")


@dataclass(frozen=True, slots=True)
class Site:
    """A site in parts: what the checks and the repairs work on.

    The whole document is only ever assembled from these, so a repaired page
    replaces one entry here and the next assembly picks it up; nothing edits
    the assembled document in place.
    """

    shell: str
    pages: tuple[tuple[str, str], ...]
    links: tuple[Link, ...]
    titles: dict[str, str] = field(default_factory=dict)
    name: str = ""

    @property
    def slugs(self) -> list[str]:
        return [slug for slug, _ in self.pages]

    def document(self) -> str:
        return assemble(
            self.shell,
            [element for _, element in self.pages],
            links=self.links,
            slugs=self.slugs,
            titles=self.titles,
            site=self.name,
        )

    def with_page(self, slug: str, element: str) -> Site:
        return replace(
            self,
            pages=tuple((s, element if s == slug else e) for s, e in self.pages),
        )

    @classmethod
    def read(cls, document: str) -> Site:
        """A stored site, taken back apart."""
        plain = strip_ours(document)
        pages = tuple(pages_of(plain))
        titles = {slug: _attribute(element, "data-title") or slug for slug, element in pages}
        region = _NAV_REGION.search(plain)
        links = tuple(
            Link(unescape(label).strip(), unescape(href))
            for href, label in (_NAV_LINK.findall(region.group(1)) if region else [])
        )
        titled = _TITLE.search(plain)
        name = unescape(titled.group(1)).strip() if titled else ""
        return cls(
            shell=shell_of(plain),
            pages=pages,
            links=links,
            titles=titles,
            name=name,
        )


class WebsiteKind:
    name = "website"
    label = "Website"
    description = (
        "A website: a landing page, a one-page site for a product, an event or "
        "a campaign, or a site of several pages for a business, a restaurant, a "
        "clinic, a school, a studio or a portfolio. Use it whenever somebody "
        "asks for a website, a web page, a landing page or a homepage."
    )
    canvas = DESKTOP
    # Scripts for the menu, the routing and the forms; forms so a contact form
    # can answer itself. Still no `allow-same-origin`: an opaque origin that
    # can reach neither a cookie nor this API.
    sandbox = SandboxPolicy(scripts=True, fonts=True, images=True, forms=True)

    def __init__(
        self,
        model: ArtifactModel,
        *,
        max_bytes: int = 6_000_000,
        search: SearchProvider | None = None,
        check: bool = True,
    ) -> None:
        self._model = model
        self._max_bytes = max_bytes
        self._search = search
        self._check = check

    async def build(self, brief: Brief) -> AsyncIterator[BuildUpdate]:
        started = perf_counter()
        context = context_of(brief)

        yield Step(label="Reading the brief", detail=brief.title)
        yield Step(label="Planning the site", detail="who it is for, the pages, the look")
        plan = await self._plan(context, wanted_pages(brief), brief.title)
        spec = spec_of(plan)
        yield Designed(
            movement=plan.movement or plan.name,
            palette=plan.palette,
            display_font=plan.display_font,
            body_font=plan.body_font,
            rationale=plan.rationale or plan.tagline,
            width=SITE_WIDTH,
            height=SITE_HEIGHT,
        )
        yield Plan(titles=tuple(page.title for page in plan.pages))
        yield Step(label="Planned it", detail=described(plan))

        # The pictures are found while the shell is written: neither needs the
        # other, and each is several seconds of waiting on somebody else.
        finding = (
            asyncio.create_task(self._photographs(plan.image_queries))
            if self._search is not None and plan.image_queries
            else None
        )
        try:
            shell = ""
            async for update in self._write_shell(plan, context):
                if isinstance(update, str):
                    shell = update
                else:
                    yield update
            found = await _settled(finding)
        finally:
            if finding is not None and not finding.done():
                finding.cancel()
        if found:
            yield Step(label="Found photographs", detail=f"{len(found)} of them")

        pages: dict[int, str] = {}
        async for update in self._write_pages(plan, shell, found, context, pages):
            yield update
        site = Site(
            shell=shell,
            pages=tuple((page.slug, pages[i]) for i, page in enumerate(plan.pages) if i in pages),
            links=tuple(link for link in plan.links if still_there(link, pages, plan)),
            titles=plan.titles,
            name=plan.name,
        )
        if not site.pages:
            raise ArtifactUnavailable("None of the site's pages could be written.")

        photos = _named_photos(found)
        outcome: dict[str, Any] = {}
        async for update in self._make_it_work(site, photos, outcome):
            yield update
        site, findings, note = outcome["site"], outcome["findings"], outcome["note"]

        html = _with_photos(site.document(), photos)
        if len(html.encode()) > self._max_bytes:
            findings = (*findings, "The site is larger than it should be to store.")
        yield Finished(
            built=Built(
                html=html,
                spec=spec,
                model=self._model.name,
                build_ms=int((perf_counter() - started) * 1000),
                findings=tuple(findings),
                note=note,
                summary=_summary(site),
            )
        )

    async def revise(
        self, *, html: str, spec: DesignSpec, instruction: str
    ) -> AsyncIterator[BuildUpdate]:
        """Change a site: its words, its look, or which pages it has.

        Changes are made to the part they belong to. A word or a colour is a
        find-and-replace; a new page is written against the stylesheet the
        site already has and added to the nav; a page that needs a different
        structure is rewritten on its own. The rest is untouched by
        construction, because somebody asking for a new page is looking at a
        site they largely like.
        """
        started = perf_counter()
        plain, photos = detach_named(html)
        site = Site.read(plain)
        if not site.pages:
            raise ArtifactUnavailable("This site has no pages to change.")

        yield Step(label="Working out the change", detail=instruction[:70])
        document = strip_ours(plain)
        asked = (
            f'<user_context type="change">{instruction}</user_context>\n\n'
            f"The site's pages are: {', '.join(site.slugs)}.\n\nTHE DOCUMENT:\n\n{document}"
        )
        answered = await self._model.decide(SITE_CHANGE_SYSTEM, asked, max_tokens=8000)
        action = str(answered.get("action") or "edit").strip().lower()

        if action == "remove_page":
            site = _remove_pages(site, answered)
            yield Step(label="Removed a page", detail=f"{len(site.pages)} left")
        elif action == "add_page":
            page = _page_from(answered, taken=site.slugs)
            yield Step(label="Writing the new page", detail=page.title)
            element = await self._one_page(
                page,
                _stylesheet_of(site.shell),
                _site_brief(site),
                photos,
                change_context(instruction),
            )
            site = _add_page(site, page, element, str(answered.get("after") or ""))
            yield Step(label="Added a page", detail=f"{len(site.pages)} now")
        elif action == "rewrite_page":
            slug = str(answered.get("slug") or "").strip()
            if slug not in site.slugs:
                raise ArtifactUnavailable(
                    "That page is not on this site. It has been left as it was."
                )
            page = Page(
                slug=slug,
                title=site.titles.get(slug, slug),
                nav="",
                purpose=str(answered.get("instruction") or instruction),
            )
            yield Step(label="Rewriting a page", detail=page.title)
            element = await self._one_page(
                page,
                _stylesheet_of(site.shell),
                _site_brief(site),
                photos,
                change_context(instruction),
            )
            site = site.with_page(slug, element)
        else:
            edits = read_edits(answered)
            if not edits:
                raise ArtifactUnavailable(
                    "That change could not be worked out. The site has been left as it was."
                )
            edited, problems = apply_edits(document, edits)
            if problems:
                raise ArtifactUnavailable(
                    f"That change could not be applied: {problems[0]} "
                    "The site has been left as it was."
                )
            site = Site.read(edited)
            yield Step(label="Changed the site", detail="")

        outcome: dict[str, Any] = {}
        async for update in self._make_it_work(site, photos, outcome):
            yield update
        site, findings, note = outcome["site"], outcome["findings"], outcome["note"]

        yield Finished(
            built=Built(
                html=reattach_named(site.document(), photos),
                spec=spec,
                model=self._model.name,
                build_ms=int((perf_counter() - started) * 1000),
                findings=tuple(findings),
                note=note,
            )
        )

    # --- the plan -------------------------------------------------------

    async def _plan(self, context: str, pages: int, title: str) -> SitePlan:
        asked = context
        if pages:
            asked += f"\n\nThe site has exactly {pages} page{'' if pages == 1 else 's'}."
        for attempt in range(2):
            plan = read_plan(await self._model.decide(DESIGN_SYSTEM, asked, max_tokens=5000), title)
            if plan.pages:
                return fitted(plan, pages)
            logger.info("site plan came back without pages on attempt %d", attempt + 1)
        raise ArtifactUnavailable("Could not work out what this site should be.")

    # --- the shell ------------------------------------------------------

    async def _write_shell(self, plan: SitePlan, context: str) -> AsyncIterator[BuildUpdate | str]:
        """Stream the shell, then hand back the cleaned document as a string.

        Twice at most. A shell that ran out of room ends mid-stylesheet, and
        a site assembled into half a stylesheet is not a site; the second go
        is asked to be tighter.
        """
        request = shell_request(plan, context)
        for attempt in range(2):
            written = Written()
            async for update in self._narrate(
                SHELL_SYSTEM, request, written, label="Building the design system"
            ):
                yield update
            shell = _ensure_marks(scrub_invented_images(strip_fence(written.text)))
            if _whole(shell):
                yield shell
                return
            logger.info("site shell came back incomplete on attempt %d", attempt + 1)
            request += (
                "\n\nYour last attempt ran out of room before `</html>`. Keep the "
                "stylesheet tighter -- fewer variations, no repeated rules -- and "
                "make sure the document is complete."
            )
        raise ArtifactUnavailable("The site's design could not be written in full.")

    # --- the pages ------------------------------------------------------

    async def _write_pages(
        self,
        plan: SitePlan,
        shell: str,
        found: list[tuple[str, Photo]],
        context: str,
        pages: dict[int, str],
    ) -> AsyncIterator[BuildUpdate]:
        """Every page, several at a time, reported in order as they land."""
        stylesheet = _stylesheet_of(shell)
        brief = plan_brief(plan)
        photos = _named_photos(found)
        limit = asyncio.Semaphore(AT_ONCE)
        total = len(plan.pages)

        async def write(index: int) -> tuple[int, str | None]:
            async with limit:
                try:
                    return index, await self._one_page(
                        plan.pages[index],
                        stylesheet,
                        brief,
                        photos,
                        context,
                        photo_brief(found, index),
                    )
                except ArtifactUnavailable as exc:
                    if index == 0:
                        raise
                    # A page that will not be written is left out, and its
                    # link with it. A site one page short is still a site; a
                    # site with a dead page in its menu is broken.
                    logger.info("dropping page %s: %s", plan.pages[index].slug, exc)
                    return index, None

        yield Step(label="Writing the pages", detail=f"0 of {total}")
        pending = [asyncio.create_task(write(i)) for i in range(total)]
        reported, settled = 0, set()
        try:
            for finished in asyncio.as_completed(pending):
                index, element = await finished
                settled.add(index)
                if element is not None:
                    pages[index] = element
                # Held back until everything before it has arrived. Pages
                # finish out of order; a site that appears out of sequence is
                # worse than one that appears slowly.
                while reported in settled:
                    if reported in pages:
                        yield Part(
                            index=len([i for i in pages if i < reported]),
                            total=total,
                            title=plan.pages[reported].title,
                            html=_preview(shell, pages[reported], plan, photos),
                        )
                    reported += 1
                    yield Step(label="Writing the pages", detail=f"{reported} of {total}")
        finally:
            for task in pending:
                task.cancel()

    async def _one_page(
        self,
        page: Page,
        stylesheet: str,
        site_brief: str,
        photos: dict[str, str],
        context: str,
        described: str = "",
    ) -> str:
        system = "\n".join(
            [
                PAGE_SYSTEM.replace("{slug}", page.slug)
                .replace("{title}", page.title)
                .replace("{pages}", site_brief.split("\n", 1)[0]),
                "",
                "THE STYLESHEET YOU ARE WRITING AGAINST",
                stylesheet,
            ]
        )
        request = "\n\n".join(
            part
            for part in (
                context,
                site_brief,
                page_brief(page),
                described or photo_names(photos),
            )
            if part
        )
        last: ArtifactUnavailable | None = None
        for _ in range(2):
            written = Written()
            try:
                async for _piece in self._model.write(system, request, written):
                    pass
            except ArtifactUnavailable as exc:
                last = exc
                continue
            return normalise_page(written.text, page.slug, page.title)
        raise last or ArtifactUnavailable(f"The {page.title} page could not be written.")

    # --- making it work -------------------------------------------------

    async def _make_it_work(
        self, site: Site, photos: dict[str, str], outcome: dict[str, Any]
    ) -> AsyncIterator[BuildUpdate]:
        """Open it, repair the parts that are wrong, and say so as it happens.

        The result is left in `outcome`: the site as it ended up, what is
        still wrong with it, and a sentence for the person if it is shown
        despite a problem.
        """

        def settle(current: Site, left: Sequence[str], note: str) -> None:
            outcome["site"], outcome["findings"], outcome["note"] = current, tuple(left), note

        settle(site, (), "")
        if not self._check:
            return

        for attempt in range(FIX_ATTEMPTS + 1):
            yield Step(
                label="Opening it in a browser" if attempt == 0 else "Opening it again",
                detail="every page, on a desktop and a phone",
            )
            try:
                result = await check_site(reattach_named(site.document(), photos), site.slugs)
            except RasterUnavailable:
                logger.info("no browser to check the site in; shipping unchecked")
                settle(site, (), "This site was not opened in a browser before you saw it.")
                return

            if result.ok:
                pages = len(site.pages)
                yield Step(
                    label="It works",
                    detail=f"{pages} page{'' if pages == 1 else 's'}, on a desktop and a phone",
                )
                settle(site, (), "")
                return
            if attempt == FIX_ATTEMPTS:
                settle(site, result.summary(site.slugs), survivable(result))
                return

            first = [
                *result.shell_complaints(),
                *(c for s in result.pages_to_fix() for c in result.page_complaints(s)),
            ]
            yield Step(label="Fixing what broke", detail=first[0][:90] if first else "")
            site = await self._repair(site, result)
            settle(site, (), "")

    async def _repair(self, site: Site, result: SiteCheck) -> Site:
        """Send each problem to the part it belongs to, all at once."""
        stylesheet = _stylesheet_of(site.shell)
        jobs: list[asyncio.Task[tuple[str, str | None]]] = []

        async def shell() -> tuple[str, str | None]:
            written = Written()
            request = fix_request(result.shell_complaints(), site.shell, "THE SHELL")
            async for _ in self._model.write(FIX_SHELL_SYSTEM, request, written, temperature=0.1):
                pass
            mended = _ensure_marks(scrub_invented_images(strip_fence(written.text)))
            return "", mended if _whole(mended) else None

        async def page(slug: str) -> tuple[str, str | None]:
            element = dict(site.pages)[slug]
            written = Written()
            request = fix_request(
                result.page_complaints(slug),
                element,
                "THE PAGE",
                context=f"THE STYLESHEET IT IS WRITTEN AGAINST\n{stylesheet}",
            )
            async for _ in self._model.write(FIX_PAGE_SYSTEM, request, written, temperature=0.1):
                pass
            return slug, normalise_page(written.text, slug, site.titles.get(slug, slug))

        if result.shell_complaints():
            jobs.append(asyncio.create_task(shell()))
        for slug in result.pages_to_fix():
            if slug in site.slugs:
                jobs.append(asyncio.create_task(page(slug)))

        for done in await asyncio.gather(*jobs, return_exceptions=True):
            if isinstance(done, BaseException):
                # A repair that failed leaves that part as it was. The check
                # after this says whether that still matters.
                logger.info("a site repair failed: %s", done)
                continue
            which, mended = done
            if mended is None:
                continue
            site = replace(site, shell=mended) if not which else site.with_page(which, mended)
        return site

    # --- the calls ------------------------------------------------------

    async def _photographs(self, queries: Sequence[str]) -> list[tuple[str, Photo]]:
        """One picture per query, found three at a time, in the plan's order."""
        assert self._search is not None
        search = self._search
        limit = asyncio.Semaphore(3)

        async def one(query: str) -> tuple[str, Photo | None]:
            async with limit:
                return query, await find_photo(search, query)

        found = await asyncio.gather(*(one(q) for q in list(queries)[:MAX_PHOTOS]))
        return [(query, photo) for query, photo in found if photo is not None]

    async def _narrate(
        self, system: str, user: str, into: Written, *, label: str
    ) -> AsyncIterator[BuildUpdate]:
        """One long call, narrated. A minute of silence reads as a hang."""
        written = 0
        last_said = 0.0
        yield Step(label=label, detail="")
        async for piece in self._model.write(system, user, into):
            written += len(piece)
            yield Chunk(text=piece)
            now = perf_counter()
            if now - last_said >= 0.5:
                last_said = now
                yield Step(label=label, detail=f"{written // 1000} KB so far")


def _site_brief(site: Site) -> str:
    pages = ", ".join(f"#/{slug} ({site.titles.get(slug, slug)})" for slug in site.slugs)
    return f"{pages}\n\nTHE SITE\nName: {site.name}"


def _summary(site: Site) -> str:
    """What the site is, in a line the chat model can say truthfully."""
    titles = [site.titles.get(slug, slug) for slug in site.slugs]
    if len(titles) == 1:
        sections = [link.label for link in site.links]
        listed = f", with sections for {', '.join(sections)}" if sections else ""
        return f"a one-page website{listed}"
    return f"a website of {len(titles)} pages: {', '.join(titles)}"


# --- the build's own helpers ----------------------------------------------------


async def _settled(
    finding: asyncio.Task[list[tuple[str, Photo]]] | None,
) -> list[tuple[str, Photo]]:
    """The photographs, or none. A site without the pictures it hoped for is
    still a site; a search that fell over is not a reason to lose it."""
    if finding is None:
        return []
    try:
        return await finding
    except Exception:  # noqa: BLE001 - pictures are optional, the site is not
        logger.exception("looking for the site's photographs failed")
        return []


# --- the document -------------------------------------------------------------


def _ensure_marks(shell: str) -> str:
    """The shell with a place for the pages, whatever it wrote.

    Told to leave `<!--PAGES-->` in an empty `<main>`, a model sometimes
    writes a page anyway, or leaves `<main>` out. Either way the pages go
    where the site's content belongs.
    """
    if pages_of(shell):
        shell = shell_of(shell)
    if PAGES_MARK in shell:
        return shell
    main = re.search(r"<main\b[^>]*>(.*?)</main\s*>", shell, re.IGNORECASE | re.S)
    if main is not None:
        return shell[: main.start(1)] + PAGES_MARK + shell[main.end(1) :]
    footer = re.search(r"<footer\b", shell, re.IGNORECASE)
    if footer is not None:
        at = footer.start()
        return f'{shell[:at]}<main id="site">{PAGES_MARK}</main>\n{shell[at:]}'
    ended = shell.lower().rfind("</body>")
    if ended != -1:
        return f'{shell[:ended]}<main id="site">{PAGES_MARK}</main>\n{shell[ended:]}'
    return shell


def _whole(shell: str) -> bool:
    lowered = shell.lower()
    return "</html>" in lowered and "<style" in lowered and "</style>" in lowered


def _stylesheet_of(shell: str) -> str:
    """The design's own stylesheet, which every page is written against."""
    return "\n".join(block.strip() for block in _STYLE.findall(shell))


def _attribute(element: str, name: str) -> str:
    opened = re.match(r"<section\b[^>]*>", element, re.IGNORECASE)
    if opened is None:
        return ""
    found = re.search(rf'\b{name}\s*=\s*"([^"]*)"', opened.group(0))
    return unescape(found.group(1)) if found else ""


def _named_photos(found: Sequence[tuple[str, Photo]]) -> dict[str, str]:
    return {variable_for(i): photo.data_uri for i, (_, photo) in enumerate(found)}


def _uses(document: str, name: str) -> bool:
    return re.search(rf"var\(\s*{re.escape(name)}\s*[,)]", document) is not None


def _with_photos(document: str, photos: dict[str, str]) -> str:
    """Only the pictures something on the site actually shows.

    A photograph is a few hundred kilobytes. One found and never used is dead
    weight in every download and every share, so it stays out -- as a hole,
    so the ones after it keep their names.
    """
    return reattach_named(
        document, {name: uri for name, uri in photos.items() if _uses(document, name)}
    )


def _preview(shell: str, element: str, plan: SitePlan, photos: dict[str, str]) -> str:
    """One page, alone in the shell, for the build view.

    No scripts at all, the shell's included: it is shown in a frame that runs
    none, as a picture of the page, and a script left in it is only a console
    error per thumbnail. A lone page needs no routing to decide what to show.
    """
    document = place_nav(_SCRIPTS.sub("", shell), plan.links).replace(PAGES_MARK, element, 1)
    return reattach_named(
        document, {name: uri for name, uri in photos.items() if _uses(element, name)}
    )


def _page_from(answered: dict[str, Any], *, taken: Sequence[str]) -> Page:
    title = str(answered.get("title") or answered.get("nav") or "New page").strip()[:60]
    slug = unique(slugify(str(answered.get("slug") or title), "page"), taken)
    # Prefixed with the page, because every page shares one document and an
    # id the home page already uses would send its anchor links there.
    sections = tuple(
        Section(
            id=slugify(f"{slug}-{s.get('id') or i}", f"{slug}-{i}"),
            job=str(s.get("job") or "").strip()[:400],
        )
        for i, s in enumerate((answered.get("sections") or [])[:MAX_SECTIONS], 1)
        if isinstance(s, dict)
    )
    return Page(
        slug=slug,
        title=title,
        nav=str(answered.get("nav") or title).strip()[:30],
        purpose=str(answered.get("purpose") or "").strip()[:400],
        sections=sections,
    )


def _add_page(site: Site, page: Page, element: str, after: str) -> Site:
    slugs = site.slugs
    at = slugs.index(after) + 1 if after in slugs else len(slugs)
    pages = (*site.pages[:at], (page.slug, element), *site.pages[at:])

    links = list(site.links)
    # A one-page site whose menu jumped between sections is a site of pages
    # now, and needs a way back to the first one.
    if not any(link.href == "#/home" for link in links) and "home" in slugs:
        links.insert(0, Link("Home", "#/home"))
    hrefs = [link.href for link in links]
    place = hrefs.index(f"#/{after}") + 1 if f"#/{after}" in hrefs else len(links)
    links.insert(place, Link(page.nav or page.title, f"#/{page.slug}"))
    return replace(
        site,
        pages=pages,
        links=tuple(links),
        titles={**site.titles, page.slug: page.title},
    )


def _remove_pages(site: Site, answered: dict[str, Any]) -> Site:
    raw = answered.get("slugs")
    listed = raw if isinstance(raw, list) else [answered.get("slug")]
    wanted = {str(s).strip() for s in listed if s}
    # The home page is where every link that has nowhere else to go ends up.
    wanted.discard(site.slugs[0])
    kept = tuple((slug, element) for slug, element in site.pages if slug not in wanted)
    if len(kept) == len(site.pages):
        raise ArtifactUnavailable(
            "That page is not one this site can lose. It has been left as it was."
        )
    gone = {f"#/{slug}" for slug in wanted}
    return replace(
        site,
        pages=kept,
        links=tuple(link for link in site.links if link.href not in gone),
        titles={k: v for k, v in site.titles.items() if k not in wanted},
    )
