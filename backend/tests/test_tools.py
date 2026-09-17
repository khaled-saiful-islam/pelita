"""Search and news parsing, and the contributor that puts them in the prompt."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from app.context.base import TurnContext
from app.context.contributors import ToolResultsContributor
from app.providers.base import Role, TokenBudget, ToolResult
from app.tools.news_mcp import NewsUnavailable, parse_feed
from app.tools.serpapi import SearchUnavailable, SerpApiSearch, parse_results

# --- SerpAPI parsing ----------------------------------------------------


def serp(*results: dict) -> dict:
    return {"organic_results": list(results)}


def test_organic_results_become_ranked_tool_results() -> None:
    parsed = parse_results(
        serp(
            {"title": "First", "link": "https://a.test", "snippet": "one"},
            {"title": "Second", "link": "https://b.test", "snippet": "two"},
        ),
        limit=5,
    )
    assert [r.rank for r in parsed] == [1, 2]
    assert [r.title for r in parsed] == ["First", "Second"]
    assert all(r.tool == "web_search" for r in parsed)


def test_results_without_a_title_or_link_are_skipped_not_fatal() -> None:
    """A partial set of sources is more useful than none."""
    parsed = parse_results(
        serp(
            {"title": "Good", "link": "https://a.test", "snippet": "x"},
            {"title": "", "link": "https://b.test"},
            {"title": "No link"},
            {"title": "Also good", "link": "https://c.test"},
        ),
        limit=5,
    )
    assert [r.title for r in parsed] == ["Good", "Also good"]


def test_a_missing_snippet_is_empty_not_absent() -> None:
    parsed = parse_results(serp({"title": "T", "link": "https://a.test"}), limit=5)
    assert parsed[0].snippet == ""


def test_long_snippets_are_truncated() -> None:
    parsed = parse_results(
        serp({"title": "T", "link": "https://a.test", "snippet": "x" * 900}), limit=5
    )
    assert len(parsed[0].snippet) == 400


def test_the_limit_is_respected() -> None:
    many = serp(*[{"title": f"R{i}", "link": f"https://{i}.test"} for i in range(20)])
    assert len(parse_results(many, limit=3)) == 3


def test_an_empty_response_yields_nothing() -> None:
    assert parse_results({}, limit=5) == []
    assert parse_results({"organic_results": []}, limit=5) == []


# --- SerpAPI transport --------------------------------------------------


def patch_http(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = transport
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


async def test_search_without_a_key_says_so_rather_than_failing_obscurely() -> None:
    with pytest.raises(SearchUnavailable, match="SERPAPI_KEY"):
        await SerpApiSearch(api_key="").search("anything", limit=5)


async def test_an_empty_query_searches_for_nothing() -> None:
    assert await SerpApiSearch(api_key="k").search("   ", limit=5) == []


@pytest.mark.parametrize(
    ("status", "fragment"),
    [(401, "rejected the API key"), (429, "quota"), (500, "error")],
)
async def test_http_errors_become_readable(monkeypatch, status, fragment) -> None:
    patch_http(monkeypatch, lambda r: httpx.Response(status, text="nope"))
    with pytest.raises(SearchUnavailable, match=fragment):
        await SerpApiSearch(api_key="k").search("query", limit=5)


async def test_a_timeout_is_reported_as_such(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    patch_http(monkeypatch, handler)
    with pytest.raises(SearchUnavailable, match="timed out"):
        await SerpApiSearch(api_key="k").search("query", limit=5)


async def test_a_successful_search_returns_results(monkeypatch) -> None:
    payload = serp({"title": "Hit", "link": "https://hit.test", "snippet": "s"})
    patch_http(monkeypatch, lambda r: httpx.Response(200, json=payload))
    results = await SerpApiSearch(api_key="k").search("query", limit=5)
    assert results[0].title == "Hit"


# --- news feed parsing --------------------------------------------------


def feed(*entries: dict) -> str:
    return json.dumps({"entries": list(entries)})


def test_entries_become_news_items() -> None:
    items = parse_feed(
        feed(
            {
                "title": "Something happened - The Star",
                "link": "https://thestar.test/1",
                "summary": "<p>Body <b>text</b></p>",
                "published": "Tue, 16 Sep 2026 10:00:00 GMT",
            }
        ),
        max_items=6,
    )
    assert items[0].title == "Something happened - The Star"
    assert items[0].url == "https://thestar.test/1"
    assert items[0].published_at.startswith("Tue")


def test_the_publisher_is_taken_from_the_title_suffix() -> None:
    """Google News has no source field; the title suffix is the reliable place."""
    items = parse_feed(
        feed({"title": "Headline - Malaysiakini", "link": "https://x.test"}), max_items=6
    )
    assert items[0].source == "Malaysiakini"


def test_an_explicit_source_object_wins_over_the_title() -> None:
    items = parse_feed(
        feed(
            {
                "title": "Headline - Wrong",
                "link": "https://x.test",
                "source": {"title": "Right"},
            }
        ),
        max_items=6,
    )
    assert items[0].source == "Right"


def test_a_title_without_a_suffix_falls_back() -> None:
    items = parse_feed(feed({"title": "Plain headline", "link": "https://x.test"}), max_items=6)
    assert items[0].source == "News"


def test_html_is_stripped_from_summaries() -> None:
    items = parse_feed(
        feed({"title": "T", "link": "https://x.test", "summary": "<a href='#'>Read</a> this"}),
        max_items=6,
    )
    assert items[0].snippet == "Read this"


def test_max_items_is_respected() -> None:
    many = feed(*[{"title": f"H{i}", "link": f"https://{i}.test"} for i in range(20)])
    assert len(parse_feed(many, max_items=4)) == 4


@pytest.mark.parametrize(
    "payload",
    [
        '{"items": [{"title": "T", "link": "https://x.test"}]}',
        '{"articles": [{"title": "T", "url": "https://x.test"}]}',
        '[{"title": "T", "link": "https://x.test"}]',
    ],
)
def test_other_server_shapes_are_tolerated(payload: str) -> None:
    """MCP_NEWS_COMMAND is swappable, so the parser cannot assume one shape."""
    assert len(parse_feed(payload, max_items=6)) == 1


def test_non_json_is_reported_as_unavailable() -> None:
    with pytest.raises(NewsUnavailable, match="not JSON"):
        parse_feed("<html>nope</html>", max_items=6)


def test_no_usable_entries_is_reported_as_unavailable() -> None:
    with pytest.raises(NewsUnavailable, match="no usable"):
        parse_feed(feed({"title": "", "link": ""}), max_items=6)


# --- the contributor ----------------------------------------------------


def ctx(results: tuple[ToolResult, ...], tools_budget: int = 2048) -> TurnContext:
    return TurnContext(
        conversation_id=uuid4(),
        user_id=uuid4(),
        user_message="what happened?",
        model="gpt-4o-mini",
        budget=TokenBudget(memory=512, tools=tools_budget, history=4096),
        tool_results=results,
    )


def result(rank: int, snippet: str = "body") -> ToolResult:
    return ToolResult(
        tool="web_search",
        title=f"Title {rank}",
        url=f"https://example.test/{rank}",
        snippet=snippet,
        rank=rank,
    )


async def test_no_results_contributes_nothing() -> None:
    assert await ToolResultsContributor().contribute(ctx(())) == []


async def test_results_are_numbered_and_the_model_is_told_to_cite() -> None:
    messages = await ToolResultsContributor().contribute(ctx((result(1), result(2))))
    assert len(messages) == 1
    assert messages[0].role is Role.SYSTEM
    body = messages[0].content
    assert "[1]" in body and "[2]" in body
    assert "cite" in body.lower()
    assert "https://example.test/1" in body


async def test_results_stop_at_the_token_budget() -> None:
    big = tuple(result(i, snippet="word " * 400) for i in range(1, 11))
    body = (await ToolResultsContributor().contribute(ctx(big, tools_budget=300)))[0].content
    assert "[1]" in body
    assert "[10]" not in body


async def test_the_contributor_sits_between_memory_and_history() -> None:
    assert ToolResultsContributor().order == 300
