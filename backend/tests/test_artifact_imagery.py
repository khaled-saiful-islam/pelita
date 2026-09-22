"""Getting a real photograph onto a poster.

A model cannot produce one and cannot know one exists, so the rule is that a
poster may only use a picture it was given. These cover the giving.
"""

from __future__ import annotations

import base64
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.artifacts.imagery import (
    MAX_EDGE,
    WANTS_A_PICTURE,
    Photo,
    attach_photo,
    detach_photo,
    find_photo,
    photo_brief,
    reattach,
)
from app.providers.base import ToolResult
from app.tools.serpapi import SearchUnavailable


def a_picture(width: int = 2400, height: int = 1600, mode: str = "RGB") -> bytes:
    image = Image.new(mode, (width, height), (120, 80, 40) if mode == "RGB" else (120, 80, 40, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeSearch:
    name = "web_search"

    def __init__(self, urls: list[str], *, fail: str | None = None) -> None:
        self._urls = urls
        self._fail = fail
        self.queries: list[str] = []

    async def search(self, query: str, *, limit: int):  # pragma: no cover - unused
        return []

    async def search_images(self, query: str, *, limit: int) -> list[ToolResult]:
        self.queries.append(query)
        if self._fail:
            raise SearchUnavailable(self._fail)
        return [
            ToolResult(
                tool="image_search",
                title="A picture",
                url=f"https://page.test/{i}",
                snippet="",
                rank=i,
                thumbnail_url=url,
                image_url=url,
            )
            for i, url in enumerate(self._urls, 1)
        ]


def transport(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return httpx.MockTransport(handle)


@pytest.fixture
def mocked(monkeypatch):
    """Patch the client `find_photo` opens, so nothing reaches the network.

    The address check is satisfied too: these hosts do not resolve at all, and
    the guard that refuses private addresses refuses unresolvable ones as well.
    Its own behaviour is tested separately, below.
    """
    import socket as socket_module

    def install(routes: dict[str, httpx.Response]):
        original = httpx.AsyncClient

        def build(*args, **kwargs):
            kwargs["transport"] = transport(routes)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", build)
        monkeypatch.setattr(
            socket_module, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
        )

    return install


IMAGE_HEADERS = {"content-type": "image/png"}


async def test_a_photograph_is_found_downscaled_and_embedded(mocked) -> None:
    """Embedded rather than linked: the document stays one file that prints and
    downloads, a shared poster does not report its readers to a stranger's
    host, and the picture cannot vanish from under it later."""
    url = "https://pictures.test/big.png"
    mocked({url: httpx.Response(200, content=a_picture(), headers=IMAGE_HEADERS)})

    photo = await find_photo(FakeSearch([url]), "night market lanterns")

    assert photo is not None
    assert photo.data_uri.startswith("data:image/jpeg;base64,")
    assert max(photo.width, photo.height) == MAX_EDGE
    assert photo.source == "https://page.test/1"


async def test_the_next_candidate_is_tried_when_one_fails(mocked) -> None:
    """One result being a dead link is the normal case, not an error."""
    dead, alive = "https://pictures.test/gone.png", "https://pictures.test/ok.png"
    mocked({
        dead: httpx.Response(404),
        alive: httpx.Response(200, content=a_picture(600, 400), headers=IMAGE_HEADERS),
    })

    photo = await find_photo(FakeSearch([dead, alive]), "kopi")

    assert photo is not None
    assert (photo.width, photo.height) == (600, 400)


async def test_something_that_is_not_an_image_is_refused(mocked) -> None:
    url = "https://pictures.test/page.html"
    mocked({url: httpx.Response(200, content=b"<html>not a picture</html>",
                                headers={"content-type": "text/html"})})

    assert await find_photo(FakeSearch([url]), "kopi") is None


async def test_no_search_results_is_not_an_error(mocked) -> None:
    mocked({})
    assert await find_photo(FakeSearch([]), "kopi") is None


async def test_search_being_down_is_not_an_error(mocked) -> None:
    """A poster without the photograph it hoped for is still a poster."""
    mocked({})
    assert await find_photo(FakeSearch([], fail="no key"), "kopi") is None


async def test_an_empty_query_never_searches(mocked) -> None:
    mocked({})
    search = FakeSearch(["https://pictures.test/a.png"])
    assert await find_photo(search, "   ") is None
    assert search.queries == []


async def test_transparency_is_flattened(mocked) -> None:
    """A PNG with an alpha channel goes black over a dark poster."""
    url = "https://pictures.test/logo.png"
    mocked({url: httpx.Response(200, content=a_picture(400, 400, "RGBA"), headers=IMAGE_HEADERS)})

    photo = await find_photo(FakeSearch([url]), "kopi")

    assert photo is not None
    decoded = base64.b64decode(photo.data_uri.split(",", 1)[1])
    with Image.open(BytesIO(decoded)) as image:
        assert image.mode == "RGB"


# --- putting it in and taking it out ------------------------------------


PHOTO = Photo(data_uri="data:image/jpeg;base64,AAAA", source="https://page.test/1",
              width=800, height=600)

POSTER = (
    "<!DOCTYPE html><html><head><style>\n:root {\n  --ground: #101010;\n}\n"
    ".canvas{width:794px}\n</style></head><body><div class='canvas'></div></body></html>"
)


def test_a_photograph_goes_into_the_variables_the_css_already_uses() -> None:
    attached = attach_photo(POSTER, PHOTO)
    assert '--photo: url("data:image/jpeg;base64,AAAA");' in attached
    assert "--ground: #101010;" in attached


def test_a_document_with_no_root_block_gets_one() -> None:
    bare = (
        "<!DOCTYPE html><html><head><style>.canvas{width:794px}</style>"
        "</head><body></body></html>"
    )
    attached = attach_photo(bare, PHOTO)
    assert ":root {" in attached
    assert "--photo:" in attached


def test_it_comes_back_out_again() -> None:
    """Every round-trip after the first sends the document back to the model,
    and a base64 image costs more than everything else in the request."""
    attached = attach_photo(POSTER, PHOTO)
    plain, uri = detach_photo(attached)

    assert uri == PHOTO.data_uri
    assert "data:image" not in plain
    assert "--ground: #101010;" in plain


def test_and_goes_back_in() -> None:
    attached = attach_photo(POSTER, PHOTO)
    plain, uri = detach_photo(attached)
    assert detach_photo(reattach(plain, uri))[1] == PHOTO.data_uri


def test_a_document_without_one_detaches_to_itself() -> None:
    assert detach_photo(POSTER) == (POSTER, "")


def test_the_model_is_told_about_the_picture_but_never_given_it() -> None:
    brief = photo_brief([PHOTO])
    assert "var(--photo)" in brief
    assert "800x600" in brief
    assert PHOTO.data_uri not in brief


def test_several_pictures_are_all_named() -> None:
    """Asked for "a few food images", the poster gets a few."""
    photos = [
        Photo(data_uri=f"data:image/jpeg;base64,P{i}", source="", width=800, height=600)
        for i in range(3)
    ]
    brief = photo_brief(photos)

    assert "var(--photo)" in brief
    assert "var(--photo-2)" in brief
    assert "var(--photo-3)" in brief
    assert "Use every one of them" in brief
    assert all(photo.data_uri not in brief for photo in photos)


def test_no_pictures_says_nothing() -> None:
    assert photo_brief([]) == ""


@pytest.mark.parametrize(
    "instruction",
    ["add an image in the background", "put a photo behind the title", "use a picture"],
)
def test_a_change_that_sounds_like_it_wants_a_picture(instruction: str) -> None:
    assert WANTS_A_PICTURE.search(instruction)


@pytest.mark.parametrize("instruction", ["make it warmer", "bigger date", "remove the border"])
def test_a_change_that_does_not(instruction: str) -> None:
    assert not WANTS_A_PICTURE.search(instruction)


# --- where a picture may come from --------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://pictures.test/a.png",  # not https
        "https://localhost/a.png",
        "https://127.0.0.1/a.png",
        "https://169.254.169.254/latest/meta-data/",  # the cloud metadata service
        "https://10.0.0.5/a.png",
        "https://192.168.1.1/a.png",
        "https://[::1]/a.png",
        "https://0.0.0.0/a.png",
        "not a url at all",
    ],
)
def test_a_picture_may_not_come_from_somewhere_private(url: str) -> None:
    """These URLs come from a search engine, which is to say from anybody. A
    server that fetches whatever it is handed will fetch its own metadata
    service and hand the result back as a photograph."""
    from app.artifacts.imagery import reaches_the_public_internet

    assert reaches_the_public_internet(url) is False


def test_a_name_that_resolves_somewhere_private_is_refused(monkeypatch) -> None:
    """Resolved rather than pattern-matched: `127.0.0.1` has a hundred
    spellings and a DNS name pointing at it has infinitely many."""
    import socket as socket_module

    from app.artifacts.imagery import reaches_the_public_internet

    monkeypatch.setattr(
        socket_module,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    assert reaches_the_public_internet("https://sneaky.test/a.png") is False


def test_a_name_that_answers_with_one_good_address_and_one_bad_is_refused(
    monkeypatch,
) -> None:
    """Answering with a public address and a private one is the attack."""
    import socket as socket_module

    from app.artifacts.imagery import reaches_the_public_internet

    monkeypatch.setattr(
        socket_module,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.1.2.3", 443)),
        ],
    )
    assert reaches_the_public_internet("https://mixed.test/a.png") is False


def test_an_ordinary_public_picture_is_allowed(monkeypatch) -> None:
    import socket as socket_module

    from app.artifacts.imagery import reaches_the_public_internet

    monkeypatch.setattr(
        socket_module, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    assert reaches_the_public_internet("https://pictures.test/a.png") is True


# --- when the model writes a URL anyway ---------------------------------


def test_an_invented_url_is_pointed_at_the_photograph_we_have() -> None:
    """Told a variable holds the picture, a model still sometimes writes a
    stock URL it has seen a thousand times. Refusing the whole poster over it
    means somebody who asked for a picture gets no picture."""
    from app.artifacts.imagery import use_the_real_photograph

    document = (
        '<html><head><link href="https://fonts.googleapis.com/css2?family=Lora">'
        "<style>.bg{background-image:url('https://images.unsplash.com/photo-123?w=1536')}"
        "</style></head><body></body></html>"
    )
    fixed, swapped = use_the_real_photograph(document)

    assert swapped == 1
    assert "background-image:var(--photo)" in fixed.replace(" ", "")
    assert "unsplash" not in fixed
    # The fonts stylesheet is a link, not an image, and is left alone.
    assert "fonts.googleapis.com" in fixed


def test_a_document_with_no_invented_urls_is_untouched() -> None:
    from app.artifacts.imagery import use_the_real_photograph

    document = "<html><head><style>.bg{background-image:var(--photo)}</style></head></html>"
    assert use_the_real_photograph(document) == (document, 0)


def test_the_photograph_wins_when_the_model_declares_the_variable_too() -> None:
    """CSS takes the last declaration of a custom property. A model told the
    variable exists sometimes declares it as well — as `--photo: var(--photo)`,
    which is self-referential, which CSS discards, which leaves a poster with a
    photograph embedded in it and nothing on screen.

    A real poster this happened to: "Add one image: beach with sunset in the
    BG" produced a document containing the picture and showing none of it.
    """
    document = (
        "<html><head><style>\n:root {\n  --ground: #0A1B3D;\n"
        "  --photo: var(--photo);\n}\n.bg{background-image:var(--photo)}\n"
        "</style></head><body></body></html>"
    )

    attached = attach_photo(document, PHOTO)

    assert attached.count("--photo:") == 1
    assert "--photo: var(--photo)" not in attached
    assert f'--photo: url("{PHOTO.data_uri}");' in attached
    # And ours is the last word inside the block.
    root = attached[attached.index(":root") : attached.index("}", attached.index(":root"))]
    assert root.rstrip().endswith(";")
    assert root.index("--photo") > root.index("--ground")


def test_a_second_attach_does_not_stack_declarations() -> None:
    once = attach_photo(POSTER, PHOTO)
    twice = attach_photo(once, PHOTO)
    assert twice.count("--photo:") == 1


def test_the_model_is_told_not_to_declare_it() -> None:
    brief = photo_brief([PHOTO])
    assert "Do NOT declare" in brief
    assert "behind everything else" in brief


def test_an_invented_url_is_removed_when_there_is_no_picture_for_it() -> None:
    """A model given no photograph writes one every time. Refusing the whole
    change over it loses work the person asked for; the poster falls back to
    the gradient underneath, which is what it would have had anyway.

    From a real failure: the image search timed out, the model wrote an
    unsplash.com URL, and "add one image in the BG" was thrown away.
    """
    from app.artifacts.imagery import drop_invented_images

    document = (
        '<html><head><link href="https://fonts.googleapis.com/css2?family=Lora">'
        "<style>.bg{background-image:url('https://images.unsplash.com/photo-150?ixlib=rb')}"
        "</style></head><body></body></html>"
    )
    fixed, dropped = drop_invented_images(document)

    assert dropped == 1
    assert "unsplash" not in fixed
    assert "background-image:none" in fixed.replace(" ", "")
    assert "fonts.googleapis.com" in fixed


async def test_the_search_is_tried_twice_before_giving_up(mocked) -> None:
    """Image search is the slowest thing the provider does and times out often
    enough that giving up on the first try loses a picture asked for by name."""
    mocked({"https://pictures.test/a.png": httpx.Response(
        200, content=a_picture(400, 400), headers=IMAGE_HEADERS
    )})

    class FlakyOnce(FakeSearch):
        def __init__(self, urls):
            super().__init__(urls)
            self._first = True

        async def search_images(self, query, *, limit):
            if self._first:
                self._first = False
                raise SearchUnavailable("The search provider timed out.")
            return await super().search_images(query, limit=limit)

    photo = await find_photo(FlakyOnce(["https://pictures.test/a.png"]), "kopi")
    assert photo is not None
