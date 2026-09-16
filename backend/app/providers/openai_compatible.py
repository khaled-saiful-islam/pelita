"""The only provider implementation the template needs.

Speaks the OpenAI chat-completions wire format over raw httpx. No vendor SDK is
imported here or anywhere else, which is what makes "point it at any
OpenAI-compatible endpoint" a property of the code rather than a promise in a
README.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.core.tokens import count_message_tokens, count_tokens
from app.providers.base import (
    ChatRequest,
    Completion,
    FinishEvent,
    FinishReason,
    LLMProvider,
    ProviderError,
    ProviderInfo,
    StreamEvent,
    TokenEvent,
    Usage,
    UsageEvent,
    UsageSource,
    messages_to_wire,
)

logger = logging.getLogger(__name__)

_SSE_DATA_PREFIX = "data:"
_SSE_DONE = "[DONE]"


def _finish_reason(raw: str | None) -> FinishReason:
    match raw:
        case "length":
            return FinishReason.LENGTH
        case None | "stop":
            return FinishReason.STOP
        case _:
            return FinishReason.STOP


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        # Set to False the first time a provider rejects stream_options, so the
        # rest of the process stops sending it. Ollama and some vLLM builds do.
        self._send_stream_options = True
        self.info = ProviderInfo(
            name="openai-compatible",
            model=model,
            base_url=self._base_url,
            supports_usage_in_stream=True,
        )

    # -- wire helpers ----------------------------------------------------

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _payload(self, req: ChatRequest, *, stream: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": req.model or self._model,
            "messages": messages_to_wire(req.messages),
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "stream": stream,
        }
        if stream and self._send_stream_options:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _raise_for_status(self, response: httpx.Response, body: str) -> None:
        detail = body.strip()[:400] or response.reason_phrase
        logger.warning("provider returned %s: %s", response.status_code, detail)
        if response.status_code == 401:
            raise ProviderError(
                "The model rejected the API key. Check LLM_API_KEY in your .env.",
                status_code=401,
            )
        if response.status_code == 404:
            raise ProviderError(
                f"No chat-completions endpoint at {self._base_url}. Check LLM_BASE_URL.",
                status_code=404,
            )
        if response.status_code == 429:
            raise ProviderError(
                "The model is rate limiting requests. Try again shortly.", status_code=429
            )
        raise ProviderError(
            f"The model returned an error ({response.status_code}).",
            status_code=response.status_code,
        )

    # -- streaming -------------------------------------------------------

    async def stream_chat(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        """Yield events until the upstream response ends.

        Cancellation is the caller's job: closing this generator closes the
        underlying HTTP response, which is what actually stops the model.
        """
        prompt_tokens_estimate = count_message_tokens(req.messages, self._model)
        completed: list[str] = []
        reported_usage: Usage | None = None
        finish: FinishReason = FinishReason.STOP

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async for event in self._stream_once(client, req, completed):
                    if isinstance(event, UsageEvent):
                        reported_usage = event.usage
                        continue
                    if isinstance(event, FinishEvent):
                        finish = event.reason
                        continue
                    yield event
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError("The model timed out before responding.") from exc
        except httpx.HTTPError as exc:
            logger.warning("provider transport error: %s", exc)
            raise ProviderError("Could not reach the model. Check LLM_BASE_URL.") from exc

        text = "".join(completed)
        usage = reported_usage or Usage(
            prompt_tokens=prompt_tokens_estimate,
            completion_tokens=count_tokens(text, self._model),
            source=UsageSource.ESTIMATED,
        )
        yield UsageEvent(usage=usage)
        yield FinishEvent(reason=finish)

    async def _stream_once(
        self,
        client: httpx.AsyncClient,
        req: ChatRequest,
        sink: list[str],
    ) -> AsyncIterator[StreamEvent]:
        url = f"{self._base_url}/chat/completions"
        async with client.stream(
            "POST", url, headers=self._headers, json=self._payload(req, stream=True)
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode(errors="replace")
                rejected_options = (
                    response.status_code == 400
                    and "stream_options" in body
                    and self._send_stream_options
                )
                if rejected_options:
                    # Provider does not understand stream_options. Drop it for the
                    # rest of this process and fall back to estimated usage.
                    logger.info("provider rejected stream_options; disabling and retrying")
                    self._send_stream_options = False
                    self.info = ProviderInfo(
                        name=self.info.name,
                        model=self.info.model,
                        base_url=self.info.base_url,
                        supports_usage_in_stream=False,
                    )
                    async for event in self._stream_once(client, req, sink):
                        yield event
                    return
                self._raise_for_status(response, body)

            async for line in response.aiter_lines():
                event = self._parse_line(line, sink)
                if event is not None:
                    yield event

    def _parse_line(self, line: str, sink: list[str]) -> StreamEvent | None:
        line = line.strip()
        if not line or not line.startswith(_SSE_DATA_PREFIX):
            return None
        data = line[len(_SSE_DATA_PREFIX) :].strip()
        if data == _SSE_DONE:
            return None
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            logger.debug("skipping unparseable stream chunk: %r", data[:120])
            return None

        if usage := chunk.get("usage"):
            return UsageEvent(
                usage=Usage(
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                    source=UsageSource.PROVIDER,
                )
            )

        choices = chunk.get("choices") or []
        if not choices:
            return None
        choice = choices[0]
        if reason := choice.get("finish_reason"):
            return FinishEvent(reason=_finish_reason(reason))
        text = (choice.get("delta") or {}).get("content")
        if text:
            sink.append(text)
            return TokenEvent(text=text)
        return None

    # -- non-streaming ---------------------------------------------------

    async def complete(self, req: ChatRequest) -> Completion:
        url = f"{self._base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url, headers=self._headers, json=self._payload(req, stream=False)
                )
                if response.status_code >= 400:
                    self._raise_for_status(response, response.text)
                body = response.json()
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError("The model timed out before responding.") from exc
        except httpx.HTTPError as exc:
            logger.warning("provider transport error: %s", exc)
            raise ProviderError("Could not reach the model. Check LLM_BASE_URL.") from exc

        choice = (body.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        raw_usage = body.get("usage") or {}
        if raw_usage:
            usage = Usage(
                prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
                completion_tokens=int(raw_usage.get("completion_tokens", 0)),
                source=UsageSource.PROVIDER,
            )
        else:
            usage = Usage(
                prompt_tokens=count_message_tokens(req.messages, self._model),
                completion_tokens=count_tokens(text, self._model),
                source=UsageSource.ESTIMATED,
            )
        return Completion(
            text=text, usage=usage, finish_reason=_finish_reason(choice.get("finish_reason"))
        )
