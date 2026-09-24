"""Putting a website together, and making its pages behave like pages.

A website here is one file, because a download, a share link and a new tab all
already understand one file. So "several pages" means several
`<section data-page="...">` elements in one document, and something has to
show one at a time, move between them, keep the address in step, and mark the
current link in the nav.

That something is written here rather than by the model, for the reason the
deck's size guard and the game's stage are: it is the same on every site, it
is the part that breaks if it is written fresh each time, and when it breaks
the site is not slightly worse, it is one page long. Code with tests does it
the same way every time.

What is added, and nothing else:

- the page links, where the shell left `<!--NAV-->` for them;
- a line at the very top of `<head>` that hides every page but the one the
  address names, before anything is painted -- so there is never a flash of
  five pages stacked on top of each other;
- a small stylesheet after the design's own: page transitions, scroll-reveal,
  the form's thank-you, and room under a sticky header for in-page anchors;
- one script at the end of `<body>`: routing, reveal, and forms.

Everything is marked `data-pelita`, so it can be taken out and put back when
the site is changed, and nothing of the design's own is ever touched.

Without scripts -- a thumbnail in the build view, a reader with them off --
none of it runs and every page simply shows, one after another. A site that
degrades to a long page is still a site.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import get_close_matches
from html import escape

NAV_MARK = "<!--NAV-->"
PAGES_MARK = "<!--PAGES-->"

_NAV_BLOCK = re.compile(r"<!--pelita:nav-->.*?<!--/pelita:nav-->", re.S)
# Exactly what was added and not a character more, so taking it out is the
# inverse of putting it in and a site read back assembles to the same bytes.
_OURS = re.compile(
    r"<(script|style)\b[^>]*\bdata-pelita\s*=\s*[\"'][^\"']*[\"'][^>]*>.*?</\1\s*>",
    re.S | re.IGNORECASE,
)
_SECTION_TAG = re.compile(r"<(/?)section\b[^>]*>", re.IGNORECASE)
_PAGE_OPEN = re.compile(
    r"<section\b[^>]*\bdata-page\s*=\s*[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE
)
_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.S | re.IGNORECASE)
_HANDLER = re.compile(r"""\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.IGNORECASE)
_REMOTE_IMG = re.compile(r"<img\b[^>]*\bsrc\s*=\s*[\"']?https?://[^>]*>", re.IGNORECASE)
_REMOTE_URL = re.compile(r"url\(\s*['\"]?https?://[^)'\"]*['\"]?\s*\)", re.IGNORECASE)
_PAGE_LINK = re.compile(r"""href\s*=\s*(["'])#/([^"'#?/]*)""", re.IGNORECASE)
_SLUG = re.compile(r"[^a-z0-9-]+")
_STYLE_ATTR = re.compile(r'\bstyle\s*=\s*"([^"]*)"', re.IGNORECASE)
_PHOTO_VAR = re.compile(r"var\(\s*(--photo(?:-\d+)?)\s*\)")
_CLASS = re.compile(r"""\bclass\s*=\s*["']([^"']*)["']""")


@dataclass(frozen=True, slots=True)
class Link:
    label: str
    href: str


def slugify(text: str, fallback: str) -> str:
    """Short, lowercase, and safe to put inside a selector and a script."""
    slug = _SLUG.sub("-", text.strip().lower()).strip("-")[:40]
    return slug or fallback


# --- the nav ------------------------------------------------------------


def nav_block(links: Sequence[Link]) -> str:
    inner = "".join(
        f'<a class="nav-link" href="{escape(link.href)}">{escape(link.label)}</a>' for link in links
    )
    return f"<!--pelita:nav-->{inner}<!--/pelita:nav-->"


def place_nav(document: str, links: Sequence[Link]) -> str:
    """The page links, wherever the shell said they go -- every place it said.

    Written here rather than by the shell because the shell is written before
    the pages exist and cannot know their names for certain, and because a
    page added or removed later has to appear in, or leave, the nav without
    anybody rewriting the header.
    """
    block = nav_block(links)
    if NAV_MARK in document:
        return document.replace(NAV_MARK, block)
    if _NAV_BLOCK.search(document):
        return _NAV_BLOCK.sub(lambda _: block, document)
    # A shell that forgot the marker still has a nav, usually.
    nav = re.search(r"<nav\b[^>]*>", document, re.IGNORECASE)
    if nav is not None:
        return document[: nav.end()] + block + document[nav.end() :]
    return document


def unplace_nav(document: str) -> str:
    return _NAV_BLOCK.sub(NAV_MARK, document)


# --- the pages ----------------------------------------------------------


def page_spans(document: str) -> list[tuple[str, int, int]]:
    """Every page element: its slug, where it starts, and where it ends.

    Counted by depth, because a page is a `<section>` full of `<section>`s and
    the first closing tag after the opening one is almost never its own.
    """
    spans: list[tuple[str, int, int]] = []
    position = 0
    while True:
        opened = _PAGE_OPEN.search(document, position)
        if opened is None:
            return spans
        depth, end = 0, len(document)
        for tag in _SECTION_TAG.finditer(document, opened.start()):
            depth += -1 if tag.group(1) else 1
            if depth == 0:
                end = tag.end()
                break
        spans.append((opened.group(1), opened.start(), end))
        position = end


def pages_of(document: str) -> list[tuple[str, str]]:
    """The pages, as (slug, element), in document order."""
    return [(slug, document[start:end]) for slug, start, end in page_spans(document)]


def shell_of(document: str) -> str:
    """The document with its pages and nav taken out and the markers put back.

    What the shell's author would recognise as their own, so it can be handed
    back to be fixed without every page riding along.
    """
    spans = page_spans(document)
    if spans:
        first, last = spans[0][1], spans[-1][2]
        document = document[:first] + PAGES_MARK + document[last:]
    return unplace_nav(strip_ours(document))


def normalise_page(raw: str, slug: str, title: str) -> str:
    """One page element, whatever came back, with its identity asserted.

    The model is asked for exactly one `<section data-page>` and usually
    sends it. When it sends prose first, a fence, a bare list of sections or
    a page with the wrong slug, this is where that stops mattering: the slug
    and title are the plan's, not the writer's, because the nav and the
    router were built from the plan.

    A page may not carry a script or an inline handler. Behaviour belongs to
    the shell, and a page that could run code would be a second, unreviewed
    place for it to go wrong.
    """
    text = raw.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    text = _SCRIPT.sub("", text)
    text = _HANDLER.sub("", text)
    text = show_photos(scrub_invented_images(text))

    spans = page_spans(text)
    if spans:
        _, start, end = spans[0]
        body = text[start:end]
        opening = _PAGE_OPEN.match(body)
        inner = body[opening.end() :] if opening else body
        inner = re.sub(r"</section\s*>\s*$", "", inner, flags=re.IGNORECASE)
        classes = _CLASS.search(opening.group(0)) if opening else None
    else:
        first = text.find("<")
        inner = text[first:] if first != -1 else escape(text)
        classes = None

    attributes = f'data-page="{slug}" data-title="{escape(title)}" aria-label="{escape(title)}"'
    if classes and classes.group(1).strip():
        attributes += f' class="{escape(classes.group(1).strip())}"'
    return f"<section {attributes}>{inner.strip()}\n</section>"


def scrub_invented_images(document: str) -> str:
    """Take out every picture the model wrote a URL for.

    It was told photographs arrive as variables or not at all, and it writes
    one anyway: a plausible stock URL that resolves to nothing, or to
    somebody else's picture. A missing picture falls back to the colour
    underneath it; a broken one is a hole in the page.
    """
    without = _REMOTE_IMG.sub("", document)
    return _REMOTE_URL.sub("none", without)


def show_photos(document: str) -> str:
    """Make every photograph a page names actually appear.

    Pages and the shell are written by separate calls, and each invents its
    own way of passing a picture along: the shell's `.media` shows
    `var(--img)` only when a `data-img` attribute is present, and the page
    sets `--img: var(--photo-2)` and no attribute. Every value was right and
    the hero was an empty brown box. So a photograph named anywhere in an
    element's style is also set as that element's background, directly,
    whatever either of them thought the convention was.
    """

    def show(match: re.Match[str]) -> str:
        style = match.group(1)
        named = _PHOTO_VAR.search(style)
        if named is None or "background" in style.lower():
            return match.group(0)
        joined = style.rstrip().rstrip(";")
        return f'style="{joined}; background-image: var({named.group(1)});"'

    return _STYLE_ATTR.sub(show, document)


def mend_links(document: str, slugs: Sequence[str]) -> str:
    """Point every page link at a page that exists.

    A page written in parallel with the others knows their names from the
    plan, and still writes "#/contact-us" for a page called "contact", or
    links to a "#/booking" page nobody planned. Each of those goes to the
    nearest page that exists, or home.
    """
    known = list(slugs)
    if not known:
        return document

    def mend(match: re.Match[str]) -> str:
        quote, slug = match.group(1), match.group(2)
        if slug in known:
            return match.group(0)
        close = get_close_matches(slug, known, n=1, cutoff=0.5)
        return f"href={quote}#/{close[0] if close else known[0]}"

    return _PAGE_LINK.sub(mend, document)


def dead_links(document: str, slugs: Sequence[str]) -> list[str]:
    return sorted({m.group(2) for m in _PAGE_LINK.finditer(document)} - set(slugs))


def assemble(
    shell: str,
    pages: Sequence[str],
    *,
    links: Sequence[Link],
    slugs: Sequence[str],
    titles: dict[str, str],
    site: str,
) -> str:
    """The shell, its pages, its nav, and the routing that makes them pages."""
    document = place_nav(strip_ours(shell), links)
    joined = "\n".join(pages)

    if PAGES_MARK in document:
        document = document.replace(PAGES_MARK, joined, 1)
    else:
        main = re.search(r"<main\b[^>]*>", document, re.IGNORECASE)
        footer = re.search(r"<footer\b", document, re.IGNORECASE)
        body_end = document.lower().rfind("</body>")
        if main is not None:
            document = document[: main.end()] + joined + document[main.end() :]
        elif footer is not None:
            at = footer.start()
            document = f'{document[:at]}<main id="site">{joined}</main>{document[at:]}'
        elif body_end != -1:
            document = f'{document[:body_end]}<main id="site">{joined}</main>{document[body_end:]}'
        else:
            document += f'<main id="site">{joined}</main>'

    return route(mend_links(document, slugs), slugs=slugs, titles=titles, site=site)


# --- the routing --------------------------------------------------------


def strip_ours(document: str) -> str:
    return _OURS.sub("", document)


def route(document: str, *, slugs: Sequence[str], titles: dict[str, str], site: str) -> str:
    """Add what makes one document behave like several pages.

    Idempotent: anything added before is taken out first, so a site changed
    ten times carries one router, not ten.
    """
    document = strip_ours(document)
    pages = _script_json(list(slugs))
    named = _script_json({slug: titles.get(slug, slug) for slug in slugs})

    head = _HEAD.replace("__PAGES__", pages)
    guard = _GUARD
    router = (
        _ROUTER.replace("__PAGES__", pages)
        .replace("__TITLES__", named)
        .replace("__SITE__", _script_json(site))
    )

    opened = re.search(r"<head\b[^>]*>", document, re.IGNORECASE)
    if opened is not None:
        document = document[: opened.end()] + head + document[opened.end() :]
    else:
        document = head + document

    closed = document.lower().rfind("</head>")
    at = closed if closed != -1 else 0
    document = document[:at] + guard + document[at:]

    ended = document.lower().rfind("</body>")
    if ended != -1:
        return document[:ended] + router + document[ended:]
    return document + router


def _script_json(value: object) -> str:
    """JSON that is safe inside a `<script>`: a title with `</script>` in it
    must not end the router early."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


# Before anything is painted: which page the address names, and every other
# one hidden. Also switches on the reveal styles, which is why they cannot flash
# either.
_HEAD = (
    '<script data-pelita="route-head">(function(){var P=__PAGES__;'
    "var h=location.hash||'';var s=h.indexOf('#/')===0?h.slice(2).split(/[\\/?#]/)[0]:'';"
    "if(P.indexOf(s)<0)s=P[0];var t=document.createElement('style');"
    "t.setAttribute('data-pelita','route');"
    "t.textContent='[data-page]:not([data-page=\"'+s+'\"]){display:none!important}';"
    "document.head.appendChild(t);document.documentElement.classList.add('site-live');"
    "})();</script>"
)

_GUARD = """<style data-pelita="site">
img, video { max-width: 100%; }
:where([data-page] *, .site-footer *) { min-width: 0; }
:where([data-page], .site-footer) { overflow-wrap: break-word; }
:where([style*="var(--photo"]) {
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
}
[data-page] [id] { scroll-margin-top: var(--pelita-header, 84px); }
.site-live [data-reveal] {
  opacity: 0;
  transform: translate3d(0, 18px, 0);
  transition: opacity .7s cubic-bezier(.22, 1, .36, 1), transform .7s cubic-bezier(.22, 1, .36, 1);
}
.site-live [data-reveal].is-revealed { opacity: 1; transform: none; }
@keyframes pelita-page-in {
  from { opacity: 0; transform: translate3d(0, 10px, 0); }
  to { opacity: 1; transform: none; }
}
.pelita-enter { animation: pelita-page-in .45s cubic-bezier(.22, 1, .36, 1) backwards; }
form.is-sent > :not(.form-success) { display: none !important; }
.form-success.is-shown { display: block !important; }
@media (prefers-reduced-motion: reduce) {
  .site-live [data-reveal] { opacity: 1; transform: none; transition: none; }
  .pelita-enter { animation: none; }
}
</style>"""

_ROUTER = """<script data-pelita="router">
(function () {
  var PAGES = __PAGES__;
  var TITLES = __TITLES__;
  var SITE = __SITE__;
  var root = document.documentElement;
  var framed = window.parent !== window;
  var motion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
  var reduce = !!(motion && motion.matches);
  var current = null;

  function rule(slug) {
    var style = document.querySelector('style[data-pelita="route"]');
    if (!style) {
      style = document.createElement('style');
      style.setAttribute('data-pelita', 'route');
      document.head.appendChild(style);
    }
    style.textContent = '[data-page]:not([data-page="' + slug + '"]){display:none!important}';
  }

  function pageOf(hash) {
    if (!hash || hash.indexOf('#/') !== 0) return null;
    var slug = hash.slice(2).split(/[\\/?#]/)[0];
    return PAGES.indexOf(slug) > -1 ? slug : null;
  }

  function elementOf(hash) {
    if (!hash || hash === '#' || hash.indexOf('#/') === 0) return null;
    var id = hash.slice(1);
    try { id = decodeURIComponent(id); } catch (e) {}
    return document.getElementById(id);
  }

  function mark(slug) {
    var links = document.querySelectorAll('a[href^="#/"]');
    for (var i = 0; i < links.length; i++) {
      var here = pageOf(links[i].getAttribute('href')) === slug;
      if (here) links[i].setAttribute('aria-current', 'page');
      else links[i].removeAttribute('aria-current');
    }
  }

  function tell() {
    if (!framed) return;
    try {
      var said = { source: 'pelita-site', page: current, pages: PAGES, titles: TITLES };
      window.parent.postMessage(said, '*');
    } catch (e) {}
  }

  function show(slug, keepScroll) {
    var changed = slug !== current;
    current = slug;
    rule(slug);
    mark(slug);
    root.setAttribute('data-current-page', slug);
    if (changed) {
      if (!keepScroll) window.scrollTo(0, 0);
      var page = document.querySelector('[data-page="' + slug + '"]');
      if (page && !reduce) {
        page.classList.remove('pelita-enter');
        void page.offsetWidth;
        page.classList.add('pelita-enter');
      }
      if (PAGES.length > 1 && TITLES[slug]) document.title = TITLES[slug] + ' \\u2014 ' + SITE;
      reveal();
    }
    tell();
  }

  function go(hash) {
    var slug = pageOf(hash);
    if (slug) { show(slug, false); return; }
    var target = elementOf(hash);
    if (target) {
      var holder = target.closest ? target.closest('[data-page]') : null;
      show(holder ? holder.getAttribute('data-page') : (current || PAGES[0]), true);
      target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
      return;
    }
    show(current || PAGES[0], current !== null);
  }

  // The page is shown first and the address follows, not the other way round:
  // a frame whose address cannot be changed still moves between pages.
  function visit(hash) {
    go(hash);
    if (pageOf(hash)) {
      try { if (location.hash !== hash) location.hash = hash; } catch (e) {}
    }
  }

  document.addEventListener('click', function (event) {
    if (event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var link = event.target && event.target.closest ? event.target.closest('a[href]') : null;
    if (!link) return;
    var href = link.getAttribute('href') || '';
    if (href.charAt(0) === '#') {
      event.preventDefault();
      if (href !== '#') visit(href);
      return;
    }
    // Inside a frame, anywhere else would replace the site with somebody
    // else's page. On its own, in a tab, a link is a link.
    if (framed && !/^(mailto:|tel:)/i.test(href)) event.preventDefault();
  }, true);

  // A form here never sends anything anywhere. It is checked, and what it
  // says happens next is shown in its place.
  document.addEventListener('submit', function (event) {
    var form = event.target;
    event.preventDefault();
    if (!form || !form.checkValidity) return;
    if (!form.checkValidity()) {
      if (form.reportValidity) form.reportValidity();
      return;
    }
    var next = form.nextElementSibling;
    var done = form.querySelector('.form-success') ||
      (next && next.classList && next.classList.contains('form-success') ? next : null);
    form.classList.add('is-sent');
    if (done) {
      done.hidden = false;
      done.classList.add('is-shown');
      done.setAttribute('tabindex', '-1');
      done.setAttribute('role', 'status');
      try { done.focus({ preventScroll: true }); } catch (e) {}
    }
  }, true);

  window.addEventListener('message', function (event) {
    var data = event.data;
    if (!data || data.source !== 'pelita-go' || event.source !== window.parent) return;
    if (PAGES.indexOf(data.page) > -1) visit('#/' + data.page);
  });

  window.addEventListener('hashchange', function () { go(location.hash); });

  var watcher = null;
  if (!reduce && 'IntersectionObserver' in window) {
    watcher = new IntersectionObserver(function (entries) {
      var batch = 0;
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var element = entry.target;
        var delay = Math.min(batch * 70, 350);
        batch += 1;
        element.style.transitionDelay = delay + 'ms';
        element.classList.add('is-revealed');
        watcher.unobserve(element);
        // Handed back to the design once it has arrived, so its own hover
        // transitions are not stuck behind this one's timing.
        setTimeout(function () {
          element.removeAttribute('data-reveal');
          element.classList.remove('is-revealed');
          element.style.transitionDelay = '';
        }, delay + 900);
      });
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.06 });
  }

  function reveal() {
    var waiting = document.querySelectorAll('[data-reveal]:not(.is-revealed)');
    for (var i = 0; i < waiting.length; i++) {
      if (watcher) watcher.observe(waiting[i]);
      else waiting[i].classList.add('is-revealed');
    }
  }

  function measure() {
    var header = document.querySelector('.site-header, header');
    if (header) root.style.setProperty('--pelita-header', (header.offsetHeight + 16) + 'px');
  }

  window.addEventListener('resize', measure);
  measure();
  go(location.hash || '');
  reveal();
})();
</script>"""
