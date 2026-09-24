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
import ipaddress
import logging
import re
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urlsplit

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
# A poster is not an album. Three is enough for a strip of food, a pair of
# portraits or a background plus a detail, and each one is a download and a
# couple of hundred kilobytes in the document.
MAX_PHOTOS = 3
# At most one hop. A redirect is normal for an image CDN; a chain of them is
# how a public URL ends up pointing somewhere private.
MAX_REDIRECTS = 1

_VARIABLE = "--photo"


def variable_for(index: int) -> str:
    """`--photo` for the first, `--photo-2` onward for the rest.

    The first keeps its old name so posters made before there could be several
    still work, and so the common case — one picture — reads as one word.
    """
    return _VARIABLE if index == 0 else f"{_VARIABLE}-{index + 1}"


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


async def find_photos(
    search: SearchProvider, queries: Sequence[str], *, deadline: float = 15.0
) -> list[Photo]:
    """One picture per query, in order, skipping the ones that come to nothing.

    Sequential rather than concurrent: three of them is a handful of seconds,
    and a poster build is already measured in tens.
    """
    found: list[Photo] = []
    for query in list(queries)[:MAX_PHOTOS]:
        photo = await find_photo(search, query, deadline=deadline)
        if photo is not None:
            found.append(photo)
    return found


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

    results = []
    # Two goes. Image search is the slowest thing the search provider does and
    # times out often enough that giving up on the first one loses a picture
    # somebody asked for by name.
    for attempt in range(2):
        try:
            results = await search.search_images(query, limit=CANDIDATES)
            break
        except SearchUnavailable as exc:
            if attempt:
                logger.info("no photograph for %r: %s", query, exc)
                return None
            logger.info("image search failed for %r, trying once more: %s", query, exc)
    if not results:
        return None

    # Redirects are followed by hand, so each hop can be checked.
    async with httpx.AsyncClient(timeout=deadline, follow_redirects=False) as client:
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


def reaches_the_public_internet(url: str) -> bool:
    """Whether this URL points somewhere a stranger could also reach.

    These URLs come from a search engine, which is to say from the web, which
    is to say from anybody. A server that fetches whatever it is handed will
    happily fetch its own metadata service, a database on the private network,
    or localhost — and hand the result back as a "photograph".

    So the host is resolved and the address checked before anything is
    requested. Resolved rather than pattern-matched, because `127.0.0.1` has a
    hundred spellings and a DNS name that resolves to it has infinitely many.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    try:
        found = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError):
        return False

    for *_, address in found:
        try:
            ip = ipaddress.ip_address(address[0])
        except ValueError:
            return False
        # Every address it resolves to, not just the first: a name that answers
        # with one public address and one private one is the attack.
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            logger.info("refusing a picture at a non-public address: %s", parts.hostname)
            return False
    return bool(found)


async def _fetch(client: httpx.AsyncClient, url: str, *, source: str) -> Photo | None:
    hops = 0
    try:
        while True:
            if not reaches_the_public_internet(url):
                return None
            response = await client.get(url, headers={"Accept": "image/*"})
            if response.is_redirect and response.headers.get("location"):
                # Followed by hand so every hop is checked. `follow_redirects`
                # would take the second one on trust, which is where a public
                # URL turns into a private one.
                hops += 1
                if hops > MAX_REDIRECTS:
                    return None
                url = str(response.next_request.url) if response.next_request else ""
                if not url:
                    return None
                continue
            break

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


# Any declaration of the variable, whoever wrote it.
_ANY_DECLARATION = re.compile(
    r"[ \t]*" + re.escape(_VARIABLE) + r"(?:-\d+)?\s*:[^;{}]*;[ \t]*\n?", re.IGNORECASE
)
# `:root { ... }`, so the picture can go in as the last word on the subject.
_ROOT_BLOCK = re.compile(r"(:root\s*\{)([^{}]*)(\})", re.IGNORECASE | re.S)


def attach_photos(document: str, photos: Sequence[Photo | None]) -> str:
    """Put the pictures into the document's `:root`, and make sure they stay.

    A slot may be empty. A picture's name comes from its position, so a
    picture nobody ended up using cannot simply be dropped from the list —
    that would rename every picture after it, and a slide asking for
    `--photo-2` would get somebody else's photograph. It is left out as a
    hole instead, and the names either side of it do not move.

    Two things have to be true, and only the first is obvious.

    They go in last. CSS takes the final declaration of a custom property, and
    a model told that `--photo` exists will sometimes declare it as well — once
    as `--photo: var(--photo)`, which is self-referential, which CSS treats as
    invalid, which leaves the poster with a photograph embedded in it and
    nothing on screen. That is a real poster this happened to.

    So any declaration already there is removed first, ours are appended at the
    end of the block, and there is exactly one of each.
    """
    declarations = "".join(
        f'  {variable_for(index)}: url("{photo.data_uri}");\n'
        for index, photo in enumerate(photos)
        if photo is not None
    )
    if not declarations:
        return document

    root = _ROOT_BLOCK.search(document)
    if root is not None:
        cleaned = _ANY_DECLARATION.sub("", root.group(2))
        block = f"{root.group(1)}{cleaned}{declarations}{root.group(3)}"
        return document[: root.start()] + block + document[root.end() :]

    # No :root to extend. Give it one, immediately inside the stylesheet.
    style = re.search(r"<style[^>]*>", document, re.IGNORECASE)
    if style is None:
        return document
    without = _ANY_DECLARATION.sub("", document)
    at = re.search(r"<style[^>]*>", without, re.IGNORECASE)
    if at is None:  # pragma: no cover - the tag was just found
        return document
    return without[: at.end()] + f"\n:root {{\n{declarations}}}\n" + without[at.end() :]


def attach_photo(document: str, photo: Photo) -> str:
    """One picture, which is the common case."""
    return attach_photos(document, [photo])


# The declaration `attach_photo` writes, so it can be taken back out again.
_DECLARATION = re.compile(
    r'\s*' + re.escape(_VARIABLE) + r'(?:-\d+)?\s*:\s*url\(\s*"(data:[^"]+)"\s*\)\s*;',
    re.IGNORECASE,
)


def detach_photos(document: str) -> tuple[str, list[str]]:
    """The document without its pictures, and the pictures.

    Every model round-trip after the first sends the document back, and a
    base64 image in it costs more than everything else in the request put
    together. So they come out, the model works on the rest, and they go back.
    """
    uris = [match.group(1) for match in _DECLARATION.finditer(document)]
    return (_DECLARATION.sub("", document) if uris else document), uris


_NAMED = re.compile(
    r'\s*(' + re.escape(_VARIABLE) + r'(?:-\d+)?)\s*:\s*url\(\s*"(data:[^"]+)"\s*\)\s*;',
    re.IGNORECASE,
)


def detach_named(document: str) -> tuple[str, dict[str, str]]:
    """The document without its pictures, and each picture by its name.

    By name rather than in order, because the order is not the naming. A
    picture nobody ended up using is left out as a hole, so a document can
    hold `--photo` and `--photo-3` with nothing between them -- and putting
    those back as the first and second picture renames the third to
    `--photo-2`, which leaves whatever asked for `--photo-3` with nothing.
    """
    named = {m.group(1).lower(): m.group(2) for m in _NAMED.finditer(document)}
    return (_NAMED.sub("", document) if named else document), named


def reattach_named(document: str, named: dict[str, str]) -> str:
    """Put pictures back under exactly the names they were taken out with."""
    if not named:
        return document
    slots: dict[int, str] = {}
    for name, uri in named.items():
        suffix = name[len(_VARIABLE) :].lstrip("-")
        slots[int(suffix) - 1 if suffix.isdigit() else 0] = uri
    ordered: list[Photo | None] = [
        Photo(data_uri=slots[i], source="", width=0, height=0) if i in slots else None
        for i in range(max(slots) + 1)
    ]
    return attach_photos(document, ordered)


def reattach_all(document: str, data_uris: Sequence[str]) -> str:
    return attach_photos(
        document,
        [Photo(data_uri=uri, source="", width=0, height=0) for uri in data_uris],
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


# `url(https://...)` inside a stylesheet. Not `<link href=...>`, which is how
# the fonts arrive and is allowed.
_STYLE_URL = re.compile(
    r"url\(\s*['\"]?(https?://[^)'\"]+)['\"]?\s*\)", re.IGNORECASE
)


def drop_invented_images(document: str) -> tuple[str, int]:
    """Remove image URLs when there is no picture to put in their place.

    A model that wanted a photograph and was given none writes one anyway. If
    we cannot substitute a real picture, the poster is still better off
    without a broken box in it than refused entirely — the background falls
    back to whatever gradient is underneath, which is what it would have been.
    """
    style_start = document.lower().find("<style")
    if style_start == -1:
        return document, 0
    head, tail = document[:style_start], document[style_start:]
    swapped, count = _STYLE_URL.subn("none", tail)
    return head + swapped, count


def use_the_real_photograph(document: str) -> tuple[str, int]:
    """Point every invented image URL at the picture we actually have.

    Told that a variable holds a photograph, a model will still sometimes write
    a URL of its own — a plausible one, from a stock library it has seen a
    thousand times, which resolves to nothing or to something else entirely.

    Refusing the whole revision over it means somebody who asked for a picture
    gets no picture. Substituting is deterministic, touches only the thing that
    was wrong, and ends with the poster using the photograph that was found for
    it.
    """
    style_start = document.lower().find("<style")
    if style_start == -1:
        return document, 0
    head, tail = document[:style_start], document[style_start:]
    swapped, count = _STYLE_URL.subn(f"var({_VARIABLE})", tail)
    return head + swapped, count


# English-only, like the other pattern layers here. A miss means the change is
# made without looking for a picture, which is the common case anyway.
WANTS_A_PICTURE = re.compile(
    r"\b(image|images|photo|photos|photograph|picture|pictures|backdrop|wallpaper)\b",
    re.IGNORECASE,
)


def photo_brief(photos: Sequence[Photo]) -> str:
    """What the composing model is told. Never the bytes."""
    if not photos:
        return ""

    named = "\n".join(
        f"  `var({variable_for(index)})` — {photo.width}x{photo.height}"
        for index, photo in enumerate(photos)
    )
    several = len(photos) > 1
    return (
        f"{'Photographs have' if several else 'A photograph has'} been found for "
        f"this poster and {'are' if several else 'is'} already available as CSS "
        f"{'variables' if several else 'a variable'} holding a url() of the image:\n"
        f"{named}\n"
        "Use one with `background-image: var(--photo)`, `background-size: cover` "
        "and `background-position: center`. If the brief asks for a picture in "
        "the background, it covers the whole canvas behind everything else — "
        "not a band, not a panel, not a corner.\n"
        + (
            "Use every one of them. They were found because the brief asked for "
            "more than one, so a strip, a grid or a row of cards is what they are "
            "for.\n"
            if several
            else ""
        )
        + "Do NOT declare these variables yourself. They are already declared. "
        "Writing `--photo: var(--photo)` in `:root`, which is the tempting thing "
        "to do, is self-referential, and CSS discards it — the poster then has a "
        "photograph inside it and nothing on screen.\n"
        "Write the variable and nothing else. Do not write a URL — not an "
        "unsplash.com one, not a picsum one, not any other; you are not able to "
        "know that one exists, and one you write points at nothing or at "
        "something else entirely."
    )
