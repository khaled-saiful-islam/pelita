"""The image reader, if there is one.

Returns `None` when `VISION_MODEL` is empty, exactly as `build_tools()` returns
nothing without a search key. The upload path reads that as "images are not a
supported file type" and says so, rather than accepting a file it can never
read.

Pointing at a different vision backend is a new module implementing
`ImageReader` and one line here.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.vision.base import ImageReader
from app.vision.openai_compatible import OpenAICompatibleImageReader


def build_image_reader(settings: Settings | None = None) -> ImageReader | None:
    settings = settings or get_settings()
    if not settings.vision_enabled:
        return None
    return OpenAICompatibleImageReader(
        base_url=settings.resolved_vision_base_url,
        api_key=settings.resolved_vision_api_key,
        model=settings.vision_model,
        timeout=settings.vision_timeout_seconds,
        max_tokens=settings.vision_max_tokens,
    )
