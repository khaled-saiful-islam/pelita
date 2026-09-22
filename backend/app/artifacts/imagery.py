"""Getting a real photograph onto a poster.

A model cannot produce a photograph, and a model asked for one produces a URL
that looks plausible and resolves to nothing. So the rule is not "no images" —
it is that a poster may only use a picture it was **given**.

One is found by searching, downscaled to what the canvas can actually use, and
embedded as a data URI. Embedding rather than linking keeps three promises the
rest of this feature already makes: the document stays self-contained, so a
download and a print still work; a shared poster does not report its readers to
a third-party host; and the picture cannot disappear from under it later.

The composing model never sees the bytes. It is told a CSS variable exists and
uses it; the data goes in afterwards, because a base64 photograph in a prompt
costs more than the poster does.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from app.tools.serpapi import SearchProvider, SearchUnavailable

logger = logging.getLogger(__name__)

# Big enough to fill a poster without being noticeably soft; small enough that
# the document stays a document. A full-bleed A4 background at this width is
# roughly 120-250 KB once re-encoded.
MAX_EDGE = 1600
JPEG_QUALITY = 78
# A candidate larger than this is not downloaded at all. Nothing on a poster
# justifies pulling twelve megabytes to throw most of it away.
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
# After re-encoding. A photograph past this is dropped rather than shipped.
MAX_EMBEDDED_BYTES = 450 * 1024
CANDIDATES = 5

_VARIABLE = "--photo"


@dataclass(frozen=True, slots=True)
class Photo:
    """A picture the poster may use, and where it came from."""

    data_uri: str
    # The page it appears on, not the file. A picture with no context is not a
    # source anybody can check.
    source: str
    width: int
    height: int

    @property
    def bytes(self) -> int:
        return len(self.data_uri)


async def find_photo(
    search: SearchProvider, query: str, *, deadline: float = 15.0
) -> Photo | None:
    """The first result that downloads and decodes into something usable.

    Returns None rather than raising. A poster without the photograph it hoped
    for is still a poster; a failed request is not.
    """
    query = query.strip()
    if not query:
        return None

    try:
        results = await search.search_images(query, limit=CANDIDATES)
    except SearchUnavailable as exc:
        logger.info("no photograph for %r: %s", query, exc)
        return None

    async with httpx.AsyncClient(timeout=deadline, follow_redirects=True) as client:
        for result in results:
            url = result.image_url or result.thumbnail_url
            if not url.startswith("https://"):
                continue
            photo = await _fetch(client, url, source=result.url)
            if photo is not None:
                logger.info(
                    "photograph for %r: %dx%d, %d bytes",
                    query,
                    photo.width,
                    photo.height,
                    photo.bytes,
                )
                return photo
    return None


async def _fetch(client: httpx.AsyncClient, url: str, *, source: str) -> Photo | None:
    try:
        response = await client.get(url, headers={"Accept": "image/*"})
        if response.status_code >= 400:
            return None
        if not response.headers.get("content-type", "").startswith("image/"):
            return None
        if len(response.content) > MAX_DOWNLOAD_BYTES:
            return None
        return _encode(response.content, source=source)
    except (httpx.HTTPError, ValueError):
        # One candidate failing is the normal case, not an error worth a word
        # on screen. The next one is tried.
        return None


def _encode(raw: bytes, *, source: str) -> Photo | None:
    """Downscale, flatten and re-encode as a JPEG data URI.

    Flattened because a PNG with transparency becomes black over a dark poster,
    and re-encoded because whatever was on the web was sized for the web.
    """
    try:
        with Image.open(BytesIO(raw)) as image:
            image = image.convert("RGB")
            image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError):
        return None

    encoded = base64.b64encode(buffer.getvalue()).decode()
    if len(encoded) > MAX_EMBEDDED_BYTES:
        return None
    return Photo(
        data_uri=f"data:image/jpeg;base64,{encoded}",
        source=source,
        width=width,
        height=height,
    )


def attach_photo(document: str, photo: Photo) -> str:
    """Put the picture into the document's `:root`, where the CSS already
    expects it.

    Done here rather than in the prompt because a base64 photograph costs more
    tokens than the entire poster, and the model has no use for the bytes.
    """
    declaration = f'  {_VARIABLE}: url("{photo.data_uri}");\n'
    match = re.search(r":root\s*\{", document)
    if match is None:
        # No :root to extend. Give it one, immediately inside the stylesheet.
        style = re.search(r"<style[^>]*>", document, re.IGNORECASE)
        if style is None:
            return document
        block = f"\n:root {{\n{declaration}}}\n"
        return document[: style.end()] + block + document[style.end() :]
    return document[: match.end()] + "\n" + declaration + document[match.end() :]


# The declaration `attach_photo` writes, so it can be taken back out again.
_DECLARATION = re.compile(
    r'\s*' + re.escape(_VARIABLE) + r'\s*:\s*url\(\s*"(data:[^"]+)"\s*\)\s*;', re.IGNORECASE
)


def detach_photo(document: str) -> tuple[str, str]:
    """The document without its photograph, and the photograph.

    Every model round-trip after the first has to send the document back, and a
    base64 image in that document costs more than everything else in the
    request put together. So it comes out, the model works on the rest, and it
    goes back in afterwards.
    """
    match = _DECLARATION.search(document)
    if match is None:
        return document, ""
    return _DECLARATION.sub("", document, count=1), match.group(1)


def reattach(document: str, data_uri: str) -> str:
    """Put a photograph back, given only its data URI."""
    if not data_uri:
        return document
    return attach_photo(document, Photo(data_uri=data_uri, source="", width=0, height=0))


# English-only, like the other pattern layers here. A miss means the change is
# made without looking for a picture, which is the common case anyway.
WANTS_A_PICTURE = re.compile(
    r"\b(image|images|photo|photos|photograph|picture|pictures|backdrop|wallpaper)\b",
    re.IGNORECASE,
)


def photo_brief(photo: Photo) -> str:
    """What the composing model is told. Never the bytes."""
    return (
        "A photograph has been found for this poster and is already available "
        f"as the CSS variable `{_VARIABLE}`, holding a url() of a "
        f"{photo.width}x{photo.height} image.\n"
        f"Use it with `background-image: var({_VARIABLE})` on the full-bleed "
        "background layer, with `background-size: cover` and "
        "`background-position: center`.\n"
        "It is a photograph, so put a scrim over it — a gradient or a flat "
        "colour at partial opacity drawn from the palette — and set every word "
        "above it in a colour that clears 4.5:1 against the darkest part of "
        "the picture. Text laid straight onto a photograph is unreadable in "
        "half of it.\n"
        f"Do not write the url yourself and do not use any other image: "
        f"`var({_VARIABLE})` is the only one that exists."
    )
