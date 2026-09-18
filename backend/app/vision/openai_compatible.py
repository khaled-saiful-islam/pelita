"""Reading an image through an OpenAI-compatible vision endpoint.

The same wire format as the chat provider, with one difference: the user
message's content is a list of parts rather than a string, and one of those
parts is a `data:` URI. Any provider that serves `/chat/completions` with vision
works — OpenAI, Groq, OpenRouter, vLLM, ILMU — which is the same promise the
chat adapter makes.
"""

from __future__ import annotations

import base64
import logging

import httpx

from app.vision.base import TRANSCRIBE_PROMPT, ImageReader, VisionError, VisionInfo

logger = logging.getLogger(__name__)


class OpenAICompatibleImageReader(ImageReader):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 90.0,
        max_tokens: int = 4096,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_tokens = max_tokens
        self.info = VisionInfo(
            name="openai-compatible", model=model, base_url=self._base_url
        )

    async def read(self, data: bytes, *, media_type: str) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _data_uri(data, media_type)}},
                        {"type": "text", "text": TRANSCRIBE_PROMPT},
                    ],
                }
            ],
            # Zero: this is a transcription. A creative reading of an invoice is
            # a wrong reading of an invoice.
            "temperature": 0.0,
            "max_tokens": self._max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=self._headers,
                    json=payload,
                )
                if response.status_code >= 400:
                    self._raise_for_status(response)
                body = response.json()
        except VisionError:
            raise
        except httpx.TimeoutException as exc:
            raise VisionError(
                "Reading the image timed out. Try a smaller or simpler image."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("vision transport error: %s", exc)
            raise VisionError(
                "Could not reach the vision model. Check VISION_BASE_URL."
            ) from exc

        choice = (body.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        return _strip_control_tokens(text).strip()

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _raise_for_status(self, response: httpx.Response) -> None:
        detail = response.text.strip()[:400] or response.reason_phrase
        logger.warning("vision model returned %s: %s", response.status_code, detail)
        if response.status_code in (401, 403):
            raise VisionError("The vision model rejected the API key.")
        if response.status_code == 404:
            raise VisionError(
                f"The vision model '{self._model}' was not found at {self._base_url}."
            )
        if response.status_code == 429:
            raise VisionError("The vision model is rate limited. Try again shortly.")
        if response.status_code == 413:
            raise VisionError("The image was too large for the vision model.")
        raise VisionError("The vision model could not read the image.")


def _data_uri(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


# Some vision models wrap their answer in control tokens. Left in, they arrive
# glued to the first line of the transcript and read as page content.
_CONTROL_TOKENS = ("<|begin_of_box|>", "<|end_of_box|>")


def _strip_control_tokens(text: str) -> str:
    for token in _CONTROL_TOKENS:
        text = text.replace(token, "")
    return text
