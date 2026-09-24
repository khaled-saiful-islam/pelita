"""A website before it exists: the plan, and what each call is told.

Split from the kind itself so the build reads as a build. Everything here is
pure -- reading what the planning call sent back, and turning the plan into
the words each later call is given -- and so is tested without a model.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.artifacts.base import Brief, DesignSpec, Swatch
from app.artifacts.imagery import Photo, variable_for
from app.artifacts.site_assembly import Link, slugify
from app.artifacts.sitetest import SiteCheck
from app.artifacts.website_prompts import (
    MAX_PAGES,
    MAX_PHOTOS,
    MAX_SECTIONS,
    SITE_HEIGHT,
    SITE_WIDTH,
)

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")
_COUNT = re.compile(r"\b(\d{1,2})\s*[- ]?\s*pages?\b", re.IGNORECASE)
ROLES = ("ground", "ink", "accent", "support", "deep", "quiet")
FALLBACK_PALETTE = ("#f6f1e9", "#1d1a16", "#c2410c", "#2f5d50", "#0f1714")


# --- what a site is, before it exists ----------------------------------------


@dataclass(frozen=True, slots=True)
class Section:
    id: str
    job: str
    nav: str = ""


@dataclass(frozen=True, slots=True)
class Page:
    slug: str
    title: str
    nav: str
    purpose: str = ""
    sections: tuple[Section, ...] = ()


@dataclass(frozen=True, slots=True)
class SitePlan:
    name: str
    tagline: str = ""
    audience: str = ""
    voice: str = ""
    movement: str = ""
    rationale: str = ""
    palette: tuple[str, ...] = FALLBACK_PALETTE
    display_font: str = "Fraunces"
    body_font: str = "Manrope"
    motif: str = ""
    pages: tuple[Page, ...] = ()
    image_queries: tuple[str, ...] = ()

    @property
    def slugs(self) -> list[str]:
        return [page.slug for page in self.pages]

    @property
    def titles(self) -> dict[str, str]:
        return {page.slug: page.title for page in self.pages}

    @property
    def links(self) -> list[Link]:
        """What the nav links to: pages, or on a one-page site, its sections."""
        if len(self.pages) > 1:
            return [Link(page.nav or page.title, f"#/{page.slug}") for page in self.pages]
        sections = self.pages[0].sections if self.pages else ()
        named = [Link(s.nav, f"#{s.id}") for s in sections if s.nav]
        if named:
            return named
        # A one-page plan that named nothing for the nav still has sections
        # worth jumping to; the first is the hero and is where you already are.
        return [Link(label_of(s.id), f"#{s.id}") for s in sections[1:5]]


def wanted_pages(brief: Brief) -> int:
    """How many pages, if the person said. Zero means the plan decides."""
    if brief.count:
        return max(1, min(MAX_PAGES, brief.count))
    said = _COUNT.search(f"{brief.brief} {brief.title}")
    return max(1, min(MAX_PAGES, int(said.group(1)))) if said else 0


# --- reading the plan ---------------------------------------------------------


def read_plan(raw: dict[str, Any], title: str) -> SitePlan:
    """A plan from whatever the model sent. Tolerant: a missing field is a
    plainer site, never a failed one."""
    used_ids: set[str] = set()
    pages: list[Page] = []
    taken: list[str] = []
    for index, item in enumerate(raw.get("pages") or []):
        if not isinstance(item, dict) or len(pages) >= MAX_PAGES:
            continue
        name = str(item.get("title") or item.get("nav") or "").strip()[:60]
        fallback = "home" if index == 0 else f"page-{index + 1}"
        wanted_slug = slugify(str(item.get("slug") or name), fallback)
        slug = "home" if not pages else unique(wanted_slug, taken)
        taken.append(slug)
        sections = []
        for raw_section in (item.get("sections") or [])[:MAX_SECTIONS]:
            if not isinstance(raw_section, dict):
                continue
            fallback_id = f"{slug}-section-{len(sections) + 1}"
            wanted = slugify(str(raw_section.get("id") or ""), fallback_id)
            section_id = (
                wanted if wanted not in used_ids else unique(f"{slug}-{wanted}", list(used_ids))
            )
            used_ids.add(section_id)
            sections.append(
                Section(
                    id=section_id,
                    job=str(raw_section.get("job") or "").strip()[:400],
                    nav=str(raw_section.get("nav") or "").strip()[:30],
                )
            )
        pages.append(
            Page(
                slug=slug,
                title=name or ("Home" if slug == "home" else label_of(slug)),
                nav=str(item.get("nav") or name).strip()[:30],
                purpose=str(item.get("purpose") or "").strip()[:400],
                sections=tuple(sections),
            )
        )

    palette = tuple(
        colour.strip() for colour in raw.get("palette") or [] if _HEX.match(str(colour).strip())
    )[:6]
    queries = raw.get("image_queries")
    return SitePlan(
        name=str(raw.get("name") or title).strip()[:80] or title,
        tagline=str(raw.get("tagline") or "").strip()[:200],
        audience=str(raw.get("audience") or "").strip()[:200],
        voice=str(raw.get("voice") or "").strip()[:120],
        movement=str(raw.get("movement") or "").strip()[:80],
        rationale=str(raw.get("rationale") or "").strip()[:300],
        palette=palette if len(palette) >= 3 else FALLBACK_PALETTE,
        display_font=_face(raw.get("display_font"), "Fraunces"),
        body_font=_face(raw.get("body_font"), "Manrope"),
        motif=str(raw.get("motif") or "").strip()[:200],
        pages=tuple(pages),
        image_queries=tuple(
            str(q).strip()[:200]
            for q in (queries if isinstance(queries, list) else [])
            if str(q).strip()
        )[:MAX_PHOTOS],
    )


def fitted(plan: SitePlan, pages: int) -> SitePlan:
    """The number of pages the person asked for, when they asked."""
    if pages and len(plan.pages) > pages:
        return replace(plan, pages=plan.pages[:pages])
    return plan


def unique(slug: str, taken: Sequence[str]) -> str:
    if slug not in taken:
        return slug
    n = 2
    while f"{slug}-{n}" in taken:
        n += 1
    return f"{slug}-{n}"


def _face(value: Any, fallback: str) -> str:
    """A family name that is safe to put in a URL and a stylesheet."""
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", "", str(value or "")).strip()[:40]
    return cleaned or fallback


def label_of(slug: str) -> str:
    return slug.replace("-", " ").strip().capitalize() or "Section"


def spec_of(plan: SitePlan) -> DesignSpec:
    return DesignSpec(
        movement=plan.movement or plan.name,
        rationale=plan.rationale,
        palette=tuple(
            Swatch(name=ROLES[i] if i < len(ROLES) else f"colour-{i + 1}", hex=colour)
            for i, colour in enumerate(plan.palette)
        ),
        display_font=plan.display_font,
        body_font=plan.body_font,
        motif=plan.motif,
        width=SITE_WIDTH,
        height=SITE_HEIGHT,
        shape="responsive",
        image_queries=plan.image_queries,
    )


def described(plan: SitePlan) -> str:
    count = len(plan.pages)
    kind = "one page" if count == 1 else f"{count} pages"
    return f"{kind} · {plan.movement}" if plan.movement else kind


def still_there(link: Link, pages: dict[int, str], plan: SitePlan) -> bool:
    """A page link whose page could not be written goes with it."""
    if not link.href.startswith("#/"):
        return True
    slug = link.href[2:]
    return any(page.slug == slug and i in pages for i, page in enumerate(plan.pages))


# --- what the calls are told ---------------------------------------------------


def context_of(brief: Brief) -> str:
    parts = [
        f'<brief type="title">{brief.title}</brief>',
        f"<brief>{brief.brief}</brief>",
    ]
    if brief.style_hints.strip():
        parts.append(f'<brief type="style">{brief.style_hints}</brief>')
    if brief.data.strip():
        parts.append(
            '<brief type="rules">DATA. Use these exactly as written, and do not '
            f"invent anything that contradicts them:\n{brief.data}</brief>"
        )
    if brief.language:
        parts.append(
            f'<brief type="language">Every word a visitor reads is in {brief.language}.</brief>'
        )
    return "\n\n".join(parts)


def change_context(instruction: str) -> str:
    return (
        f'<user_context type="change">{instruction}</user_context>\n\n'
        "Write in the same language as the rest of the site."
    )


def plan_brief(plan: SitePlan) -> str:
    """The site, for a page writer: first line is the list of pages."""
    pages = ", ".join(f"#/{p.slug} ({p.title})" for p in plan.pages)
    lines = [
        pages,
        "",
        "THE SITE",
        f"Name: {plan.name}",
        f"The promise: {plan.tagline}",
        f"For: {plan.audience}",
        f"Voice: {plan.voice}",
        f"Direction: {plan.movement} -- {plan.rationale}",
        f"Recurring idea: {plan.motif}",
    ]
    empty = ("Direction:  -- ",)
    return "\n".join(line for line in lines if not line.endswith(": ") and line not in empty)


def page_brief(page: Page) -> str:
    lines = [f"THIS PAGE: #/{page.slug} -- {page.title}"]
    if page.purpose:
        lines.append(f"What it must achieve: {page.purpose}")
    if page.sections:
        lines.append("Its sections, in this order, with these ids:")
        lines.extend(f"{i}. #{s.id} -- {s.job}" for i, s in enumerate(page.sections, 1))
    else:
        lines.append("Decide its sections yourself: four to six of them.")
    return "\n".join(lines)


def shell_request(plan: SitePlan, context: str) -> str:
    roles = ", ".join(
        f"{ROLES[i] if i < len(ROLES) else 'extra'} {colour}"
        for i, colour in enumerate(plan.palette)
    )
    if len(plan.pages) > 1:
        navigation = "Several pages: " + ", ".join(
            f"{p.nav or p.title} (#/{p.slug})" for p in plan.pages
        )
    else:
        navigation = "One page. The nav links to its sections: " + ", ".join(
            f"{link.label} ({link.href})" for link in plan.links
        )
    return "\n\n".join(
        [
            context,
            "\n".join(
                [
                    "THE SITE YOU ARE BUILDING THE SHELL FOR",
                    f"Name: {plan.name}",
                    f"The promise: {plan.tagline}",
                    f"For: {plan.audience}",
                    f"Voice: {plan.voice}",
                    f"Direction: {plan.movement} -- {plan.rationale}",
                    f"Recurring idea: {plan.motif}",
                    f"Palette: {roles}",
                    f"Faces: {plan.display_font} for headings, {plan.body_font} for text",
                    f"Navigation: {navigation}",
                    "The call-to-action button links to the page or section that does "
                    "the site's main job (booking, buying, enquiring).",
                ]
            ),
        ]
    )


def photo_brief(found: Sequence[tuple[str, Photo]], page: int = 0) -> str:
    """The photographs, with one of them this page's own.

    Pages are written at the same time and cannot see each other's choices,
    so left to pick freely two of them lead with the same picture. Each is
    given one to lead with, in turn, and may use the rest where they fit.
    """
    if not found:
        return (
            "There are no photographs for this site. Make the page rich with colour, "
            "type, gradients, shapes and inline SVG instead -- never an image URL."
        )
    listed = "\n".join(
        f"  `var({variable_for(i)})` -- {query} ({photo.width}x{photo.height})"
        for i, (query, photo) in enumerate(found)
    )
    return (
        "PHOTOGRAPHS, already declared as CSS variables that each hold a url():\n"
        f"{listed}\n"
        'Show one directly on the element: style="background-image: var(--photo-2)" '
        'on a .media block or a hero, with role="img" and an aria-label saying '
        "what it shows. The first is the home page's hero. Do NOT declare these "
        "variables, and do not write any URL: one you write points at nothing, "
        "or at somebody else's picture.\n"
        f"THIS PAGE LEADS WITH `var({variable_for(page % len(found))})`: use it for "
        "this page's first photograph, so no two pages open on the same picture."
    )


def photo_names(photos: dict[str, str]) -> str:
    if not photos:
        return photo_brief(())
    names = ", ".join(f"`var({name})`" for name in sorted(photos))
    return (
        f"PHOTOGRAPHS the site already has, as CSS variables holding a url(): {names}. "
        'Use them as `background-image` on a `.media` element with `role="img"`. '
        "Do not declare them and do not write any URL."
    )


def fix_request(complaints: Sequence[str], part: str, heading: str, *, context: str = "") -> str:
    problems = "\n".join(f"- {c}" for c in complaints)
    parts = [f"WHAT WENT WRONG WHEN IT WAS OPENED:\n{problems}"]
    if context:
        parts.append(context)
    parts.append(f"{heading}:\n\n{part}")
    return "\n\n".join(parts)


def survivable(result: SiteCheck) -> str:
    """One sentence for the person when a site is shown with a problem left."""
    if result.froze:
        return "This site stopped responding when it was tested. Some of it may not work."
    if result.errors:
        return "This site hit an error when it was tested. Some of it may not work."
    if result.wide:
        return "Part of this site is wider than a phone screen."
    if result.empty or result.missing:
        return "A page of this site came out nearly empty."
    return ""
