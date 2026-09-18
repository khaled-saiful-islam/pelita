"""Getting an uploaded image ready to be looked at.

Three things happen before any image is sent anywhere, and they happen here so
the transcript, the thumbnail and anything added later cannot disagree about
which pixels they are talking about.
"""

from __future__ import annotations

import base64
import io
import logging

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

THUMBNAIL_MAX_EDGE = 320
_THUMBNAIL_QUALITY = 70
# A data URI lives in a database column and travels in every conversation
# response, so it is capped rather than trusted to be small.
THUMBNAIL_MAX_CHARS = 64_000


class UnreadableImage(Exception):
    """The bytes are not an image we can open. Message is shown to the user."""


def prepare(data: bytes, *, max_pixels: int, jpeg_quality: int) -> tuple[bytes, str]:
    """Return `(bytes, media_type)` ready for a vision call.

    Rotation is applied rather than left in EXIF, because a model reads the
    pixels and not the tag: a photo taken sideways is transcribed sideways, and
    the answer is confidently wrong about a page it never saw upright.

    Downscaling is about cost, not quality. A phone photo is 12 megapixels; a
    vision model bills for tiles it gains nothing from, and 2.5MP is past the
    point where more pixels produce more text.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image) or image
            if image.mode not in ("RGB", "L"):
                # JPEG has no alpha. Flatten onto white rather than dropping the
                # channel, which turns transparent regions black and hides text.
                image = _flatten(image)

            pixels = image.width * image.height
            if pixels > max_pixels:
                scale = (max_pixels / pixels) ** 0.5
                size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                image = image.resize(size, Image.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
    except UnreadableImage:
        raise
    except Exception as exc:  # noqa: BLE001 - Pillow raises a wide family
        logger.info("could not open image: %s", exc)
        raise UnreadableImage(
            "That image could not be opened. It may be corrupt or an unusual format."
        ) from exc

    return buffer.getvalue(), "image/jpeg"


def thumbnail(data: bytes) -> str | None:
    """A small JPEG data URI for the card in the transcript, or None.

    Returns None rather than raising: a missing thumbnail costs an icon, and the
    file itself has already been read by then.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image) or image
            if image.mode not in ("RGB", "L"):
                image = _flatten(image)
            image.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=_THUMBNAIL_QUALITY, optimize=True)
    except Exception:  # noqa: BLE001 - a thumbnail is never worth an error
        logger.info("could not build a thumbnail", exc_info=True)
        return None

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    uri = f"data:image/jpeg;base64,{encoded}"
    return uri if len(uri) <= THUMBNAIL_MAX_CHARS else None


def _flatten(image: Image.Image) -> Image.Image:
    converted = image.convert("RGBA")
    background = Image.new("RGBA", converted.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, converted).convert("RGB")
