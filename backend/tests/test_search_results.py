"""Everything useful Google returns, not only its links.

Shaped on the real responses behind a bad answer: the right answer ("Arsenal
crowned 2025/26 Premier League champions", dated 19 May 2026) was in the
response, but only titles and 400-character snippets reached the model, with
every date thrown away -- and the date question's own answer box, which said
"Thursday, September 24, 2026", was discarded outright.
"""

from __future__ import annotations

import httpx
import pytest

from app.tools.serpapi import SerpApiSearch, parse_results
from app.tools.web_search import WebSearchTool

EPL = {
    "organic_results": [
        {
            "position": 1,
            "title": "2024–25 Premier League",
            "link": "https://en.wikipedia.org/wiki/2024%E2%80%9325_Premier_League",
            "snippet": "Champions, Liverpool 2nd Premier League title",
        },
        {
            "position": 2,
            "title": "Arsenal crowned 2025/26 Premier League champions",
            "link": "https://www.premierleague.com/news/arsenal-champions",
            "snippet": "Arsenal crowned 2025/26 Premier League champions.",
            "date": "May 19, 2026",
        },
    ]
}


def test_an_organic_result_keeps_its_date() -> None:
    results = parse_results(EPL, limit=5)
    assert results[1].published == "May 19, 2026"
    assert results[0].published == ""


def test_the_answer_box_comes_first_and_is_citable() -> None:
    payload = {
        "answer_box": {
            "type": "time",
            "result": "Thursday, September 24, 2026",
            "date": "Date in Collin County, TX",
        },
        **EPL,
    }
    first = parse_results(payload, limit=5, query="what is today's date")[0]
    assert first.rank == 1
    assert "Thursday, September 24, 2026" in first.snippet
    # No link of its own, so the search itself is the source someone can open.
    assert first.url.startswith("https://www.google.com/search?q=")


def test_an_answer_box_with_a_link_cites_that_page() -> None:
    payload = {
        "answer_box": {
            "type": "organic_result",
            "title": "Premier League champions",
            "answer": "Arsenal",
            "link": "https://www.premierleague.com/history",
        }
    }
    [box] = parse_results(payload, limit=5, query="epl champion")
    assert box.url == "https://www.premierleague.com/history"
    assert "Arsenal" in box.snippet


def test_links_and_thumbnails_are_not_read_out_as_the_answer() -> None:
    payload = {
        "answer_box": {
            "result": "RM4.72",
            "thumbnail": "https://serpapi.com/thumb.png",
            "serpapi_link": "https://serpapi.com/search?x=1",
        }
    }
    [box] = parse_results(payload, limit=5, query="usd to myr")
    assert "RM4.72" in box.snippet
    assert "serpapi.com" not in box.snippet


def test_the_knowledge_graph_and_sports_results_are_kept() -> None:
    payload = {
        "knowledge_graph": {
            "title": "Arsenal F.C.",
            "type": "Football club",
            "description": "Arsenal are the 2025–26 Premier League champions.",
            "website": "https://www.arsenal.com",
        },
        "sports_results": {
            "title": "Arsenal",
            "game_spotlight": {"league": "Premier League", "date": "Sat, Sep 20", "score": "2 - 1"},
        },
    }
    results = parse_results(payload, limit=5, query="arsenal")
    snippets = " | ".join(r.snippet for r in results)
    assert "2025–26 Premier League champions" in snippets
    assert "2 - 1" in snippets
    assert any(r.url == "https://www.arsenal.com" for r in results)


def test_top_stories_arrive_dated_and_capped() -> None:
    payload = {
        "top_stories": [
            {
                "title": f"Story {n}",
                "link": f"https://news.test/{n}",
                "source": "The Star",
                "date": "3 hours ago",
            }
            for n in range(6)
        ]
    }
    results = parse_results(payload, limit=5, query="news")
    assert len(results) == 3
    assert results[0].published == "3 hours ago"
    assert "The Star" in results[0].snippet


def test_a_page_found_twice_is_listed_once() -> None:
    payload = {
        "top_stories": [
            {
                "title": "Arsenal crowned",
                "link": "https://www.premierleague.com/news/arsenal-champions",
            }
        ],
        **EPL,
    }
    urls = [r.url for r in parse_results(payload, limit=5)]
    assert len(urls) == len(set(urls))


def test_ranks_are_contiguous_across_every_section() -> None:
    payload = {"answer_box": {"answer": "Arsenal"}, **EPL}
    assert [r.rank for r in parse_results(payload, limit=5, query="q")] == [1, 2, 3]


def capture(monkeypatch) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=EPL)

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = transport
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return seen


@pytest.mark.parametrize(
    ("recency", "tbs"),
    [("day", "qdr:d"), ("week", "qdr:w"), ("month", "qdr:m"), ("year", "qdr:y")],
)
async def test_recency_narrows_google_to_that_window(monkeypatch, recency, tbs) -> None:
    seen = capture(monkeypatch)
    await SerpApiSearch(api_key="k").search("epl champion", limit=5, recency=recency)
    assert seen[0].url.params["tbs"] == tbs


async def test_no_recency_means_no_window(monkeypatch) -> None:
    seen = capture(monkeypatch)
    await SerpApiSearch(api_key="k").search("epl champion", limit=5)
    assert "tbs" not in seen[0].url.params


async def test_a_country_localises_the_search(monkeypatch) -> None:
    seen = capture(monkeypatch)
    await SerpApiSearch(api_key="k", country="my").search("harga minyak", limit=5)
    assert seen[0].url.params["gl"] == "my"


class RecordingSearch:
    name = "web_search"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def search(self, query: str, *, limit: int, recency: str | None = None):
        self.calls.append((query, recency))
        return parse_results(EPL, limit=limit)

    async def search_images(self, query: str, *, limit: int):  # pragma: no cover
        return []


async def test_the_tool_passes_a_known_recency_and_drops_an_invented_one() -> None:
    search = RecordingSearch()
    tool = WebSearchTool(search)
    await tool.run(query="arsenal news", recency="week")
    await tool.run(query="arsenal news", recency="fortnight")
    assert search.calls == [("arsenal news", "week"), ("arsenal news", None)]


def test_the_tool_tells_the_model_how_to_write_a_query() -> None:
    description = WebSearchTool(RecordingSearch()).description.lower()
    # The bad query behind the reported answer carried a year from memory.
    assert "year" in description
    assert "again" in description
    assert "recency" in WebSearchTool.parameters["properties"]
    assert WebSearchTool.parameters["required"] == ["query"]
