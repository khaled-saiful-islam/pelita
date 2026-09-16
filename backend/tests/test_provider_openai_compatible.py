"""The adapter is the template's central claim, so it is tested against the
wire formats real providers actually emit rather than an idealised one."""

from __future__ import annotations

import json

import httpx
import pytest

from app.providers.base import (
    ChatMessage,
    ChatRequest,
    FinishEvent,
    ProviderError,
    Role,
    TokenEvent,
    UsageEvent,
    UsageSource,
)
from app.providers.openai_compatible import OpenAICompatibleProvider


def sse(*chunks: dict | str) -> bytes:
    lines = []
    for c in chunks:
        payload = c if isinstance(c, str) else json.dumps(c)
        lines.append(f"data: {payload}\n\n")
    return "".join(lines).encode()


def delta(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}, "finish_reason": None}]}


@pytest.fixture
def request_obj() -> ChatRequest:
    return ChatRequest(
        messages=(ChatMessage(role=Role.USER, content="hello"),),
        model="test-model",
    )


async def collect(provider, req):
    return [event async for event in provider.stream_chat(req)]


async def test_streams_tokens_and_provider_usage(monkeypatch, request_obj):
    body = sse(
        delta("Hel"),
        delta("lo"),
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 2}},
        "[DONE]",
    )
    _patch_stream(monkeypatch, body)

    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1", api_key="sk-test", model="test-model"
    )
    events = await collect(provider, request_obj)

    assert [e.text for e in events if isinstance(e, TokenEvent)] == ["Hel", "lo"]
    usage = next(e.usage for e in events if isinstance(e, UsageEvent))
    assert usage.prompt_tokens == 11
    assert usage.completion_tokens == 2
    assert usage.source is UsageSource.PROVIDER
    assert isinstance(events[-1], FinishEvent)


async def test_estimates_usage_when_provider_omits_it(monkeypatch, request_obj):
    """Ollama and some vLLM builds stream without a usage block."""
    _patch_stream(monkeypatch, sse(delta("hi there"), "[DONE]"))

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1", api_key="", model="llama3.2"
    )
    events = await collect(provider, request_obj)

    usage = next(e.usage for e in events if isinstance(e, UsageEvent))
    assert usage.source is UsageSource.ESTIMATED
    assert usage.completion_tokens > 0


async def test_ignores_unparseable_chunks(monkeypatch, request_obj):
    _patch_stream(monkeypatch, sse(delta("a"), "{not json", delta("b"), "[DONE]"))

    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1", api_key="k", model="m"
    )
    events = await collect(provider, request_obj)
    assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == "ab"


async def test_missing_api_key_sends_no_auth_header():
    provider = OpenAICompatibleProvider(base_url="http://x/v1", api_key="", model="m")
    assert "Authorization" not in provider._headers  # noqa: SLF001


async def test_api_key_becomes_bearer_header():
    provider = OpenAICompatibleProvider(base_url="http://x/v1", api_key="sk-1", model="m")
    assert provider._headers["Authorization"] == "Bearer sk-1"  # noqa: SLF001


async def test_base_url_trailing_slash_is_normalised():
    provider = OpenAICompatibleProvider(base_url="http://x/v1/", api_key="k", model="m")
    assert provider.info.base_url == "http://x/v1"


@pytest.mark.parametrize(
    ("status", "fragment"),
    [(401, "API key"), (404, "LLM_BASE_URL"), (429, "rate limiting"), (500, "error")],
)
async def test_http_errors_become_readable_messages(monkeypatch, request_obj, status, fragment):
    _patch_stream(monkeypatch, b"upstream said no", status=status)
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1", api_key="k", model="m"
    )
    with pytest.raises(ProviderError) as err:
        await collect(provider, request_obj)
    assert fragment.lower() in str(err.value).lower()


async def test_stream_options_rejection_disables_and_retries(monkeypatch, request_obj):
    """Some providers 400 on stream_options. One retry, then never send it again."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if "stream_options" in payload:
            return httpx.Response(400, text='{"error":"unknown field stream_options"}')
        return httpx.Response(200, content=sse(delta("ok"), "[DONE]"))

    _patch_with_handler(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1", api_key="k", model="m"
    )

    events = await collect(provider, request_obj)
    assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == "ok"
    assert len(calls) == 2
    assert provider.info.supports_usage_in_stream is False

    calls.clear()
    await collect(provider, request_obj)
    assert "stream_options" not in calls[0]


async def test_complete_returns_text_and_usage(monkeypatch, request_obj):
    payload = {
        "choices": [{"message": {"content": "a title"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }
    _patch_with_handler(monkeypatch, lambda r: httpx.Response(200, json=payload))
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1", api_key="k", model="m"
    )
    result = await provider.complete(request_obj)
    assert result.text == "a title"
    assert result.usage.source is UsageSource.PROVIDER


async def test_timeout_is_reported_as_readable_error(monkeypatch, request_obj):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    _patch_with_handler(monkeypatch, handler)
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1", api_key="k", model="m"
    )
    with pytest.raises(ProviderError, match="timed out"):
        await collect(provider, request_obj)


# --- helpers ------------------------------------------------------------


def _patch_with_handler(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = transport
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


def _patch_stream(monkeypatch, body: bytes, status: int = 200) -> None:
    _patch_with_handler(monkeypatch, lambda request: httpx.Response(status, content=body))
