"""Reading an image.

One method, because that is the whole seam: bytes in, text out. Everything
downstream — excerpt selection, the token budget, the contributor, the card in
the transcript — already works on text, so an image that has been read is just
another document.

Why this is not the `LLMProvider` protocol: `ChatMessage.content` is a `str` by
design, and a multimodal message body is a list of typed parts. Widening it
would push that shape into every contributor, the token counter and the history
builder, for one caller. A separate protocol keeps the cost where the feature
is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class VisionError(RuntimeError):
    """The image could not be read. Carries a message meant for the user."""


@dataclass(frozen=True, slots=True)
class VisionInfo:
    name: str
    model: str
    base_url: str


@runtime_checkable
class ImageReader(Protocol):
    """Turns an image into the text it contains."""

    info: VisionInfo

    async def read(self, data: bytes, *, media_type: str) -> str:
        """Return everything readable in the image.

        Raises `VisionError` with a message worth showing when it cannot.
        """
        ...


# A transcription, not a description. The difference decides whether the answer
# to "what's the total on this invoice?" is a number or an apology: a model
# asked to *describe* a table writes "a table of charges", and the figures —
# the only reason the image was uploaded — never reach the conversation.
#
# Deliberately question-agnostic. The image is read once at upload and the text
# is what every later turn sees, so the transcript has to serve questions that
# had not been asked yet.
TRANSCRIBE_PROMPT = (
    "Transcribe everything readable in this image as plain text. "
    "Preserve structure: keep tables as rows with their column headers and every "
    "cell value, keep lists as lists, and keep labels attached to their numbers. "
    "Include all figures, units, dates and headings exactly as shown. "
    "Then, on a final line beginning 'Depicts: ', describe what the image shows "
    "in one sentence. "
    "Return only the content — no commentary, no preamble."
)
