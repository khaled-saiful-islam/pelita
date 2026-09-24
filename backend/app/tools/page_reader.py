"""Opening the pages a search found, the way a person clicks through.

A search result is Google's two lines about a page, cut short and usually
undated. The page has the paragraph that actually answers and, most of the
time, says when it was written -- which for "who is the current champion" is
the whole question. So the top few are fetched, their text is pulled out of
the markup, and the passages that match the query go to the model with the
date.

The URLs come from search results, not from the person, but a page can
redirect anywhere, so every hop is checked: http(s) on the usual ports, and
only to addresses on the public internet -- never this machine, the private
network or a cloud metadata endpoint.

Known limit: the address is checked, then connected to by name, so a host
that answers the check with a public address and the connection with a private
one (DNS rebinding) is not caught. Closing that means pinning the connection to
the checked address, which httpx does not offer without a custom transport.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import zlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from urllib.parse import urljoin, urlsplit

import httpx

from app.providers.base import ToolResult
from app.services.document_excerpts import WORD, keywords
from app.tools.page_text import Page, extract

__all__ = ["EXCERPT_CHARS", "Page", "PageReader", "extract", "passages"]

logger = logging.getLogger(__name__)

# About three paragraphs. Several pages are read per search and every one of
# them is prompt the model pays for on every round of the turn.
EXCERPT_CHARS = 1500
MAX_BYTES = 1_500_000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 6.0

# Sites that answer a fetch with a sign-in wall, a video player or an app
# shell: reading one spends a slot and returns nothing.
UNREADABLE_HOSTS = frozenset(
    {
        "google.com",
        "youtube.com",
        "youtu.be",
        "facebook.com",
        "instagram.com",
        "tiktok.com",
        "x.com",
        "twitter.com",
        "linkedin.com",
        "pinterest.com",
        "reddit.com",
    }
)
UNREADABLE_SUFFIXES = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".mp4",
    ".mp3",
    ".zip",
    ".doc",
    ".docx",
)

# Identifies itself honestly. A crawler pretending to be a browser is the
# thing site owners block first.
HEADERS = {
    "user-agent": "Mozilla/5.0 (compatible; Pelita/1.0; reads pages its search found)",
    "accept": "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.8",
    # Only what `_body` can inflate with a limit. Brotli is left off the list,
    # and a page sent in it anyway is not read.
    "accept-encoding": "gzip, deflate",
}

Resolver = Callable[[str, int], Awaitable[list[str]]]


class PageReader:
    def __init__(
        self,
        *,
        timeout: float = TIMEOUT_SECONDS,
        max_bytes: int = MAX_BYTES,
        resolve: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._resolve = resolve or _resolve
        self._transport = transport

    @staticmethod
    def worth_reading(url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return False
        host = (parts.hostname or "").removeprefix("www.").lower()
        if any(host == blocked or host.endswith(f".{blocked}") for blocked in UNREADABLE_HOSTS):
            return False
        return not parts.path.lower().endswith(UNREADABLE_SUFFIXES)

    @classmethod
    def pick(cls, results: Sequence[ToolResult], limit: int) -> list[ToolResult]:
        """The first `limit` results a fetch could get anything out of."""
        return [r for r in results if cls.worth_reading(r.url)][: max(limit, 0)]

    async def enrich(
        self, results: Sequence[ToolResult], *, query: str, limit: int
    ) -> list[ToolResult]:
        """The same results, with what their pages say attached.

        Never raises and never drops a result: a page that cannot be read
        leaves its result exactly as the search returned it.
        """
        targets = self.pick(results, limit)
        if not targets:
            return list(results)
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeout,
            headers=HEADERS,
            follow_redirects=False,
        ) as client:
            pages = await asyncio.gather(*(self._read_safely(client, r.url) for r in targets))
        read = {result.url: page for result, page in zip(targets, pages, strict=True) if page}
        return [_attach(result, read.get(result.url), query) for result in results]

    async def _read_safely(self, client: httpx.AsyncClient, url: str) -> Page | None:
        try:
            return await asyncio.wait_for(self._read(client, url), self._timeout)
        except Exception:  # noqa: BLE001 - one unreadable page must not cost the search
            logger.info("could not read %s", url, exc_info=True)
            return None

    async def _read(self, client: httpx.AsyncClient, url: str) -> Page | None:
        for _ in range(MAX_REDIRECTS + 1):
            if not await self._allowed(url):
                logger.info("not fetching %s: not a public web address", url)
                return None
            async with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                if response.status_code != 200:
                    return None
                kind = response.headers.get("content-type", "").lower()
                if "html" not in kind and "text/plain" not in kind:
                    return None
                body = await self._body(response)
                if body is None:
                    return None
                text = body.decode(response.encoding or "utf-8", errors="replace")
            return extract(text)
        return None

    async def _body(self, response: httpx.Response) -> bytes | None:
        """The page's bytes, never more than `max_bytes` of them, compressed or not.

        Read raw and inflated here, because a client's transparent decoding
        inflates each chunk in full: 50 KB of gzip is 50 MB in memory before a
        cap on the decoded stream is ever looked at. Each chunk is inflated
        only as far as the room left under the cap.
        """
        if response.is_stream_consumed:
            # A transport that read the body itself has already decoded it;
            # all that is left to do is keep to the cap.
            return bytes(response.content[: self._max_bytes])
        encoding = response.headers.get("content-encoding", "").strip().lower()
        if encoding in ("", "identity"):
            inflate = None
        elif encoding in ("gzip", "x-gzip"):
            inflate = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif encoding == "deflate":
            inflate = zlib.decompressobj()
        else:
            return None

        body = bytearray()
        async for chunk in response.aiter_raw():
            room = self._max_bytes - len(body)
            if inflate is None:
                body += chunk[:room]
            else:
                try:
                    # Output stops at `room`; the rest of the input waits in
                    # `unconsumed_tail` and is never inflated, because the
                    # cap is reached and reading ends here.
                    body += inflate.decompress(chunk, room)
                except zlib.error:
                    return None
            if len(body) >= self._max_bytes:
                break
        return bytes(body)

    async def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        try:
            port = parts.port
        except ValueError:
            return False
        if port not in (None, 80, 443):
            return False
        try:
            addresses = await self._resolve(
                parts.hostname, port or (443 if parts.scheme == "https" else 80)
            )
        except Exception:  # noqa: BLE001 - a name that does not resolve is not readable
            return False
        return bool(addresses) and all(_public(address) for address in addresses)


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _attach(result: ToolResult, page: Page | None, query: str) -> ToolResult:
    if page is None:
        return result
    excerpt = passages(page.text, query)
    if not excerpt and not page.published:
        return result
    return replace(result, excerpt=excerpt, published=result.published or page.published)


# A sentence, not a label. Table rows are short and still the answer:
# "2025-26 · Arsenal · Manchester City".
MIN_WORDS = 6


def _root(word: str) -> str:
    """A word without its plural, so "champion" finds "champions".

    Crude on purpose -- it is applied to both sides, so "news" becoming "new"
    costs nothing -- and kept here rather than in document retrieval, whose
    matching this should not quietly change.
    """
    lowered = word.lower()
    for suffix in ("'s", "es", "s"):
        if len(lowered) > 4 and lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def _matches(paragraph: str, terms: set[str]) -> int:
    """How many of the query's distinct terms the paragraph contains."""
    if not terms:
        return 0
    return len(terms & {_root(word) for word in WORD.findall(paragraph)})


def _substantive(paragraph: str) -> bool:
    return " · " in paragraph or len(paragraph.split()) >= MIN_WORDS


def passages(text: str, query: str, *, budget: int = EXCERPT_CHARS) -> str:
    """The paragraphs that mention what was asked, in page order.

    Keyword overlap, like attached documents, for the same reasons: no service,
    no index, and for "premier league champions 2025/26" it finds the right
    paragraph. A page that matches nothing gives its opening instead.
    """
    every = [p for p in text.split("\n\n") if p.strip()]
    paragraphs = [p for p in every if _substantive(p)] or every
    if not paragraphs:
        return ""
    terms = {_root(term) for term in keywords(query)}
    scored = [(_matches(p, terms), order, p) for order, p in enumerate(paragraphs)]
    relevant = [item for item in scored if item[0] > 0]
    # Equal matches go to the paragraph with more to say: a two-word label
    # naming the subject scores as well as a sentence about it.
    ranked = (
        sorted(relevant, key=lambda item: (-item[0], -min(len(item[2]), 600), item[1]))
        if relevant
        else scored
    )

    kept: list[tuple[int, str]] = []
    used = 0
    for _, order, paragraph in ranked:
        cost = len(paragraph) + 3
        if used + cost > budget:
            continue
        kept.append((order, paragraph))
        used += cost
    if not kept:
        best = ranked[0][2]
        return best[: budget - 1].rstrip() + "…"
    return " … ".join(paragraph for _, paragraph in sorted(kept))
