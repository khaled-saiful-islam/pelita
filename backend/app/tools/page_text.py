"""A web page's words, without its furniture, and the date it says it was written.

Standard library only. A real readability port would do better on odd layouts;
this does well enough on the pages search results lead to -- news, reference,
official sites -- for the price of no dependency, and it never runs a script.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Page:
    text: str
    # "19 May 2026", or "updated 20 September 2026" when only a revision date
    # is given. Empty when the page does not say -- never a guess.
    published: str = ""


# Everything that is furniture rather than the page's content.
_SKIPPED = frozenset(
    {
        "head",
        "title",
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "canvas",
        "iframe",
        "nav",
        "aside",
        "form",
        "button",
        "select",
        "dialog",
        "menu",
    }
)
# Skipped only outside an article: an article's own header holds its headline
# and its date, and the site's header holds the menu.
_CHROME = frozenset({"header", "footer"})
_CONTENT = frozenset({"article", "main"})
_BLOCKS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "li",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "table",
        "thead",
        "tbody",
        "br",
        "hr",
        "blockquote",
        "pre",
        "figcaption",
        "caption",
        "header",
        "footer",
    }
)
_CELLS = frozenset({"td", "th"})

_PUBLISHED_KEYS = frozenset(
    {
        "article:published_time",
        "og:published_time",
        "datepublished",
        "published_time",
        "pubdate",
        "publishdate",
        "publish-date",
        "date",
        "dc.date",
        "dc.date.issued",
        "parsely-pub-date",
        "sailthru.date",
        "article.published",
    }
)
_MODIFIED_KEYS = frozenset(
    {"article:modified_time", "og:updated_time", "datemodified", "last-modified"}
)
_LD_DATE = re.compile(r'"(datePublished|dateModified)"\s*:\s*"([^"]{6,40})"')


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        # Anywhere on the page, not just the line before: a section label
        # repeated down a page is furniture however far apart the copies are.
        self._seen: set[str] = set()
        self.published = ""
        self.modified = ""
        self._line: list[str] = []
        self._skip = 0
        self._content = 0
        self._chrome: list[bool] = []
        self._structured = False
        self._structured_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        self._dates_in(tag, values)
        if tag == "script" and "ld+json" in values.get("type", ""):
            self._structured = True
        if tag in _CONTENT:
            self._content += 1
        if tag in _SKIPPED:
            self._skip += 1
        elif tag in _CHROME:
            skipped = self._content == 0
            self._chrome.append(skipped)
            self._skip += int(skipped)
        if tag in _BLOCKS:
            self._flush()
        elif tag in _CELLS and self._line:
            self._line.append(" · ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._structured = False
        if tag in _SKIPPED and self._skip:
            self._skip -= 1
        elif tag in _CHROME and self._chrome:
            self._skip -= int(self._chrome.pop())
        if tag in _CONTENT and self._content:
            self._content -= 1
        if tag in _BLOCKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._structured:
            self._structured_text.append(data)
        elif not self._skip:
            self._line.append(data)

    def close(self) -> None:
        super().close()
        self._flush()
        for key, value in _LD_DATE.findall("".join(self._structured_text)):
            self._note(value, published=key == "datePublished")

    def _flush(self) -> None:
        line = " ".join("".join(self._line).split()).strip(" ·")
        self._line = []
        if len(line) >= 2 and line not in self._seen:
            self._seen.add(line)
            self.paragraphs.append(line)

    def _dates_in(self, tag: str, values: dict[str, str]) -> None:
        if tag == "meta":
            key = values.get("property") or values.get("name") or values.get("itemprop") or ""
            key = key.lower()
            if key in _PUBLISHED_KEYS:
                self._note(values.get("content", ""), published=True)
            elif key in _MODIFIED_KEYS:
                self._note(values.get("content", ""), published=False)
        elif values.get("itemprop", "").lower() == "datepublished":
            self._note(values.get("content") or values.get("datetime", ""), published=True)
        elif tag == "time" and values.get("datetime"):
            self._note(values["datetime"], published=True)

    def _note(self, raw: str, *, published: bool) -> None:
        said = human_date(raw)
        if not said:
            return
        if published and not self.published:
            self.published = said
        elif not published and not self.modified:
            self.modified = said


def extract(html: str) -> Page:
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - a malformed page yields what was read before it broke
        logger.info("page markup could not be fully parsed", exc_info=True)
    published = _dated(parser.published, parser.modified)
    return Page(text="\n\n".join(parser.paragraphs), published=published)


def _dated(published: str, modified: str) -> str:
    """Both dates when a page was revised after it was written.

    Wikipedia dates a list by the day the page was created, so "28 August
    2006" alone made a list edited yesterday look nearly twenty years old.
    """
    if published and modified and modified != published:
        return f"{published}, updated {modified}"
    if published:
        return published
    return f"updated {modified}" if modified else ""


def human_date(raw: str) -> str:
    """An ISO or email-style date as "19 May 2026", in the page's own zone.

    Not converted to UTC: an article published at 00:30 in Kuala Lumpur was
    published on that day, whatever the date was in London.
    """
    text = raw.strip()
    if not text:
        return ""
    moment: datetime | None = None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            moment = None
    if moment is None:
        return ""
    return f"{moment.day} {moment:%B %Y}"
