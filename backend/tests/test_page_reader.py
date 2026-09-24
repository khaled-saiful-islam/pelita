"""Reading the pages a search found, the way a person clicks through.

A snippet is Google's two lines about a page, cut at 400 characters and often
dateless. The page itself has the paragraph that answers, and usually says
when it was written.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers.base import ToolResult
from app.tools.page_reader import EXCERPT_CHARS, PageReader, extract, passages

ARTICLE = """
<html><head>
<title>Arsenal crowned champions</title>
<meta property="article:published_time" content="2026-05-19T21:04:00+01:00">
<style>.x{color:red}</style>
<script>var tracking = "Liverpool champions";</script>
</head><body>
<nav>Home · Fixtures · Liverpool champions archive</nav>
<header>Premier League</header>
<article>
<h1>Arsenal crowned 2025/26 Premier League champions</h1>
<p>Arsenal were crowned Premier League champions for the first time in 22 years
after Manchester City failed to beat Bournemouth.</p>
<table><tr><td>2025-26</td><td>Arsenal</td><td>Manchester City</td></tr></table>
</article>
<footer>Copyright. Liverpool champions 2024-25.</footer>
</body></html>
"""


def test_the_article_is_kept_and_the_furniture_is_not() -> None:
    page = extract(ARTICLE)
    assert "first time in 22 years" in page.text
    assert "2025-26 · Arsenal · Manchester City" in page.text
    for furniture in ("tracking", "color:red", "Fixtures", "Copyright"):
        assert furniture not in page.text


def test_the_published_date_is_read_from_the_page() -> None:
    assert extract(ARTICLE).published == "19 May 2026"


def test_a_date_in_structured_data_is_found() -> None:
    html = """<script type="application/ld+json">
    {"@type": "NewsArticle", "datePublished": "2026-09-21T08:00:00Z"}</script><p>x</p>"""
    assert extract(html).published == "21 September 2026"


def test_a_time_element_is_a_date_too() -> None:
    assert extract('<time datetime="2026-09-02">2 Sept</time><p>x</p>').published == (
        "2 September 2026"
    )


def test_a_page_with_no_date_says_nothing_rather_than_guessing() -> None:
    assert extract("<p>No date here at all.</p>").published == ""


# --- reading ------------------------------------------------------------


def result(url: str, rank: int = 1, published: str = "") -> ToolResult:
    return ToolResult(
        tool="web_search", title="t", url=url, snippet="s", rank=rank, published=published
    )


class Site:
    """A fake internet: every host resolves to a public address unless told
    otherwise, and every page is whatever the test says."""

    def __init__(self, pages: dict[str, httpx.Response], addresses: dict[str, str] | None = None):
        self.pages = pages
        self.addresses = addresses or {}
        self.fetched: list[str] = []

    async def resolve(self, host: str, port: int) -> list[str]:
        return [self.addresses.get(host, "93.184.216.34")]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.fetched.append(str(request.url))
        return self.pages.get(str(request.url), httpx.Response(404))

    def reader(self, **kwargs) -> PageReader:
        return PageReader(
            resolve=self.resolve, transport=httpx.MockTransport(self.handler), **kwargs
        )


def html(body: str, **headers: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html", **headers})


async def test_the_passage_that_answers_is_the_one_attached() -> None:
    filler = "".join(
        f"<p>Paragraph {n} about the club's kit and stadium tours.</p>" for n in range(80)
    )
    page = f"<article>{filler}<p>Arsenal crowned 2025/26 Premier League champions.</p></article>"
    site = Site({"https://news.test/a": html(page)})
    [read] = await site.reader().enrich(
        [result("https://news.test/a")], query="premier league champions 2025/26", limit=3
    )
    assert "Arsenal crowned 2025/26" in read.excerpt
    assert len(read.excerpt) <= EXCERPT_CHARS


async def test_the_page_date_fills_a_result_that_had_none() -> None:
    site = Site({"https://news.test/a": html(ARTICLE)})
    [read] = await site.reader().enrich([result("https://news.test/a")], query="arsenal", limit=3)
    assert read.published == "19 May 2026"


async def test_the_searchs_own_date_is_not_overwritten() -> None:
    site = Site({"https://news.test/a": html(ARTICLE)})
    [read] = await site.reader().enrich(
        [result("https://news.test/a", published="3 hours ago")], query="arsenal", limit=3
    )
    assert read.published == "3 hours ago"


async def test_only_the_first_few_readable_pages_are_read() -> None:
    urls = [
        "https://www.youtube.com/watch?v=1",
        "https://www.google.com/search?q=x",
        *(f"https://news.test/{n}" for n in range(5)),
    ]
    site = Site({url: html(ARTICLE) for url in urls})
    read = await site.reader().enrich(
        [result(url, rank) for rank, url in enumerate(urls, 1)], query="arsenal", limit=2
    )
    assert sorted(site.fetched) == ["https://news.test/0", "https://news.test/1"]
    assert [bool(r.excerpt) for r in read] == [False, False, True, True, False, False, False]


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104 - an address to refuse, not to bind
        "fd00::1",
    ],
)
async def test_an_address_inside_the_network_is_never_fetched(address) -> None:
    site = Site({"https://inside.test/": html(ARTICLE)}, {"inside.test": address})
    [read] = await site.reader().enrich([result("https://inside.test/")], query="x", limit=3)
    assert site.fetched == []
    assert read.excerpt == ""


@pytest.mark.parametrize(
    "url", ["http://news.test:8080/a", "ftp://news.test/a", "file:///etc/passwd"]
)
async def test_odd_ports_and_schemes_are_not_fetched(url) -> None:
    site = Site({url: html(ARTICLE)})
    await site.reader().enrich([result(url)], query="x", limit=3)
    assert site.fetched == []


async def test_a_redirect_into_the_network_is_not_followed() -> None:
    site = Site(
        {
            "https://news.test/a": httpx.Response(
                302, headers={"location": "http://inside.test/admin"}
            )
        },
        {"inside.test": "10.0.0.8"},
    )
    [read] = await site.reader().enrich([result("https://news.test/a")], query="x", limit=3)
    assert site.fetched == ["https://news.test/a"]
    assert read.excerpt == ""


async def test_a_redirect_to_a_public_page_is_followed() -> None:
    site = Site(
        {
            "https://news.test/a": httpx.Response(301, headers={"location": "/b"}),
            "https://news.test/b": html(ARTICLE),
        }
    )
    [read] = await site.reader().enrich([result("https://news.test/a")], query="arsenal", limit=3)
    assert "22 years" in read.excerpt


async def test_something_that_is_not_a_page_is_left_alone() -> None:
    site = Site(
        {
            "https://news.test/a.pdf": httpx.Response(
                200, content=b"%PDF", headers={"content-type": "application/pdf"}
            )
        }
    )
    [read] = await site.reader().enrich([result("https://news.test/a.pdf")], query="x", limit=3)
    assert read.excerpt == ""


async def test_a_page_that_fails_leaves_its_result_as_it_was() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    reader = PageReader(resolve=Site({}).resolve, transport=httpx.MockTransport(boom))
    original = result("https://news.test/a")
    assert await reader.enrich([original], query="x", limit=3) == [original]


async def test_a_page_larger_than_the_cap_is_read_only_up_to_it() -> None:
    huge = "<p>Arsenal crowned champions.</p>" + "<p>" + "x" * 3_000_000 + "</p>"
    site = Site({"https://news.test/a": html(huge)})
    [read] = await site.reader(max_bytes=100_000).enrich(
        [result("https://news.test/a")], query="arsenal champions", limit=3
    )
    assert "Arsenal crowned champions." in read.excerpt


# --- found on real pages -------------------------------------------------


def test_a_page_revised_since_it_was_written_says_both() -> None:
    """Wikipedia's structured data dates a list by the day the page was
    created. "Published 28 August 2006" on a list edited yesterday is the
    wrong signal for a rule that says newer wins."""
    html = """<script type="application/ld+json">
    {"datePublished": "2006-08-28T10:00:00Z", "dateModified": "2026-09-23T18:00:00Z"}
    </script><p>x</p>"""
    assert extract(html).published == "28 August 2006, updated 23 September 2026"


def test_the_same_date_twice_is_said_once() -> None:
    html = """<meta property="article:published_time" content="2026-09-21T08:00:00Z">
    <meta property="article:modified_time" content="2026-09-21T09:30:00Z"><p>x</p>"""
    assert extract(html).published == "21 September 2026"


def test_a_label_repeated_down_the_page_is_not_a_passage() -> None:
    """BBC Sport's F1 page gave "Formula 1 … Formula 1 … Formula 1": every
    section label matched the query, and each one beat a real paragraph."""
    labels = "".join("<p>Formula 1</p><p>Latest</p>" for _ in range(12))
    page = (
        f"<article>{labels}<p>Kimi Antonelli won the Madrid Grand Prix on 13 September, "
        "his second Formula 1 win in a row after Monza.</p></article>"
    )
    excerpt = passages(extract(page).text, "who won the most recent formula 1 race")
    assert "Antonelli won the Madrid Grand Prix" in excerpt
    assert excerpt.count("Formula 1") <= 2


def test_a_table_row_is_short_but_still_worth_keeping() -> None:
    page = "<table><tr><td>2025-26</td><td>Arsenal</td><td>Manchester City</td></tr></table>"
    assert "2025-26 · Arsenal" in passages(extract(page).text, "arsenal champions 2025-26")


def test_a_plural_on_the_page_matches_a_singular_in_the_query() -> None:
    """ "current EPL champion" missed Wikipedia's "Current champions Arsenal"
    row and quoted a paragraph about sticker albums instead."""
    page = (
        "<p>Topps held the licence to produce collectables for the Premier League, "
        "current partner since 2019.</p>"
        "<table><tr><th>Current champions</th><td>Arsenal (14th title) (2025–26)</td></tr></table>"
    )
    # Room for one of the two, so the better match has to be chosen.
    excerpt = passages(extract(page).text, "current EPL champion", budget=120)
    assert "Arsenal (14th title)" in excerpt
    assert "Topps" not in excerpt


# --- compressed bodies ----------------------------------------------------


class Streamed(httpx.AsyncByteStream):
    """A body that arrives in chunks off the wire, as a real one does.

    `httpx.Response(content=...)` is read and decoded the moment it is built,
    which would test the fake rather than the reader."""

    def __init__(self, data: bytes, size: int = 16_384) -> None:
        self._data = data
        self._size = size

    async def __aiter__(self):
        for start in range(0, len(self._data), self._size):
            yield self._data[start : start + self._size]


def gzipped(body: bytes, encoding: str = "gzip") -> httpx.Response:
    import gzip

    return httpx.Response(
        200,
        stream=Streamed(gzip.compress(body)),
        headers={"content-type": "text/html", "content-encoding": encoding},
    )


async def test_a_compressed_page_is_read() -> None:
    site = Site({"https://news.test/a": gzipped(ARTICLE.encode())})
    [read] = await site.reader().enrich([result("https://news.test/a")], query="arsenal", limit=3)
    assert "22 years" in read.excerpt


async def test_a_compression_bomb_is_inflated_only_up_to_the_cap() -> None:
    """50 MB of nothing gzips to about 50 KB. Decompressed in one call, as a
    client's transparent decoding does, it is 50 MB in memory before any cap
    is looked at."""
    import tracemalloc

    bomb = b"<p>Arsenal crowned champions.</p>" + b" " * 50_000_000
    site = Site({"https://news.test/a": gzipped(bomb)})
    tracemalloc.start()
    try:
        [read] = await site.reader(max_bytes=100_000).enrich(
            [result("https://news.test/a")], query="arsenal champions", limit=3
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert "Arsenal crowned champions." in read.excerpt
    assert peak < 10_000_000


async def test_an_encoding_it_cannot_bound_is_not_read() -> None:
    site = Site({"https://news.test/a": gzipped(ARTICLE.encode(), encoding="br")})
    [read] = await site.reader().enrich([result("https://news.test/a")], query="arsenal", limit=3)
    assert read.excerpt == ""
