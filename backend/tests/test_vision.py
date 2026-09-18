"""Reading uploaded images: preparation, the reader, and the upload path."""

from __future__ import annotations

import base64
import io

import httpx
import pytest
from PIL import Image

from app.core.config import Settings
from app.core.errors import ValidationError
from app.db.models.conversation import Conversation
from app.services.document_extract import UnsupportedDocument, classify
from app.services.document_service import DocumentService
from app.services.image_prep import THUMBNAIL_MAX_EDGE, UnreadableImage, prepare, thumbnail
from app.vision.base import TRANSCRIBE_PROMPT, ImageReader, VisionError, VisionInfo
from app.vision.openai_compatible import OpenAICompatibleImageReader
from app.vision.registry import build_image_reader


def png(width: int = 40, height: int = 30, colour: str = "red", mode: str = "RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (width, height), colour if mode != "RGBA" else (255, 0, 0, 128)).save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


class FakeReader(ImageReader):
    """Records what it was handed, so tests assert on behaviour not wiring."""

    def __init__(self, text: str = "Invoice total: RM 1,240.00") -> None:
        self.info = VisionInfo(name="fake", model="fake-vision", base_url="")
        self.text = text
        self.calls: list[tuple[int, str]] = []

    async def read(self, data: bytes, *, media_type: str) -> str:
        self.calls.append((len(data), media_type))
        return self.text


class FailingReader(FakeReader):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def read(self, data: bytes, *, media_type: str) -> str:
        raise self.error


# --- classification -----------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "media_type"),
    [
        ("photo.png", "image/png"),
        ("photo.JPG", "image/jpeg"),
        ("scan.webp", "application/octet-stream"),
        # Some clients send no useful name at all.
        ("blob", "image/png"),
    ],
)
def test_images_are_recognised_when_a_vision_model_is_configured(filename, media_type):
    assert classify(filename=filename, media_type=media_type, images=True) == "image"


def test_an_image_without_a_vision_model_says_why():
    """"Not a supported file type" would send someone looking for a converter
    when the fix is a config line."""
    with pytest.raises(UnsupportedDocument, match="no vision model is configured"):
        classify(filename="photo.png", media_type="image/png", images=False)


def test_enabling_images_does_not_change_the_other_kinds():
    assert classify(filename="a.pdf", media_type="application/pdf", images=True) == "pdf"
    assert classify(filename="a.txt", media_type="text/plain", images=True) == "text"


def test_an_unsupported_type_offers_images_only_when_they_work():
    with pytest.raises(UnsupportedDocument, match="or an image"):
        classify(filename="a.exe", media_type="application/octet-stream", images=True)
    with pytest.raises(UnsupportedDocument) as refused:
        classify(filename="a.exe", media_type="application/octet-stream", images=False)
    assert "or an image" not in str(refused.value)


# --- preparation --------------------------------------------------------


def test_an_image_is_re_encoded_as_jpeg():
    data, media_type = prepare(png(), max_pixels=1_000_000, jpeg_quality=82)
    assert media_type == "image/jpeg"
    assert Image.open(io.BytesIO(data)).format == "JPEG"


def test_a_large_image_is_downscaled_to_the_budget():
    """A phone photo is 12MP and a vision model bills for tiles it gains
    nothing from."""
    data, _ = prepare(png(2000, 2000), max_pixels=250_000, jpeg_quality=82)
    with Image.open(io.BytesIO(data)) as image:
        assert image.width * image.height <= 250_000
        # Aspect ratio survives; a squashed page transcribes badly.
        assert abs(image.width - image.height) <= 1


def test_a_small_image_is_not_upscaled():
    data, _ = prepare(png(40, 30), max_pixels=1_000_000, jpeg_quality=82)
    with Image.open(io.BytesIO(data)) as image:
        assert (image.width, image.height) == (40, 30)


def test_transparency_is_flattened_onto_white():
    """JPEG has no alpha, and dropping the channel turns transparent regions
    black — which hides any dark text sitting on them."""
    data, _ = prepare(png(mode="RGBA"), max_pixels=1_000_000, jpeg_quality=82)
    assert Image.open(io.BytesIO(data)).mode == "RGB"


def test_bytes_that_are_not_an_image_are_refused_readably():
    with pytest.raises(UnreadableImage, match="could not be opened"):
        prepare(b"not an image at all", max_pixels=1_000_000, jpeg_quality=82)


def test_a_thumbnail_is_a_bounded_data_uri():
    uri = thumbnail(png(2000, 1500))
    assert uri is not None
    assert uri.startswith("data:image/jpeg;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as image:
        assert max(image.width, image.height) <= THUMBNAIL_MAX_EDGE


def test_a_thumbnail_of_something_unreadable_is_none_not_an_error():
    """A missing thumbnail costs an icon. The file has already been read."""
    assert thumbnail(b"junk") is None


# --- the reader ---------------------------------------------------------


async def test_the_image_is_sent_as_a_data_uri_with_the_prompt(monkeypatch):
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Total: 12"}}]})

    monkeypatch.setattr(
        httpx, "AsyncClient", _client_with(httpx.MockTransport(handler))
    )
    reader = OpenAICompatibleImageReader(
        base_url="https://vision.test/v1", api_key="k", model="test-vision"
    )

    assert await reader.read(b"\x89PNG-ish", media_type="image/jpeg") == "Total: 12"

    parts = captured["messages"][0]["content"]  # type: ignore[index]
    assert parts[0]["type"] == "image_url"
    assert parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert parts[1]["text"] == TRANSCRIBE_PROMPT
    # A creative reading of an invoice is a wrong reading of an invoice.
    assert captured["temperature"] == 0.0


async def test_control_tokens_are_stripped(monkeypatch):
    """Left in, they arrive glued to the first line and read as page content."""
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _client_with(
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {"message": {"content": "<|begin_of_box|>Total: 12<|end_of_box|>"}}
                        ]
                    },
                )
            )
        ),
    )
    reader = OpenAICompatibleImageReader(
        base_url="https://vision.test/v1", api_key="", model="v"
    )
    assert await reader.read(b"x", media_type="image/jpeg") == "Total: 12"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "rejected the API key"),
        (404, "was not found"),
        (429, "rate limited"),
        (413, "too large"),
        (500, "could not read the image"),
    ],
)
async def test_each_failure_says_what_to_do_about_it(monkeypatch, status, expected):
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _client_with(
            httpx.MockTransport(lambda request: httpx.Response(status, text="nope"))
        ),
    )
    reader = OpenAICompatibleImageReader(
        base_url="https://vision.test/v1", api_key="k", model="test-vision"
    )
    with pytest.raises(VisionError, match=expected):
        await reader.read(b"x", media_type="image/jpeg")


async def test_an_unreachable_endpoint_names_the_setting(monkeypatch):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "AsyncClient", _client_with(httpx.MockTransport(boom)))
    reader = OpenAICompatibleImageReader(
        base_url="https://vision.test/v1", api_key="k", model="v"
    )
    with pytest.raises(VisionError, match="VISION_BASE_URL"):
        await reader.read(b"x", media_type="image/jpeg")


def _client_with(transport: httpx.MockTransport):
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return original(*args, transport=transport, **kwargs)

    return factory


# --- the registry -------------------------------------------------------


def test_no_vision_model_means_no_reader():
    """Which is what makes an image an unsupported file type rather than a
    broken one."""
    assert build_image_reader(Settings(vision_model="")) is None


def test_the_reader_falls_back_to_the_chat_provider_url_and_key():
    """The common case is one gateway serving both, and repeating the URL is
    one more thing to get out of step."""
    reader = build_image_reader(
        Settings(
            vision_model="ilmu-vision-v1.3",
            llm_base_url="https://api.example.ai/v1",
            llm_api_key="shared",
        )
    )
    assert reader is not None
    assert reader.info.base_url == "https://api.example.ai/v1"


def test_an_explicit_vision_endpoint_wins():
    reader = build_image_reader(
        Settings(
            vision_model="llava",
            llm_base_url="https://api.example.ai/v1",
            vision_base_url="http://localhost:11434/v1",
        )
    )
    assert reader is not None
    assert reader.info.base_url == "http://localhost:11434/v1"


# --- the upload path ----------------------------------------------------


@pytest.fixture
async def conversation(session, db_user) -> Conversation:
    record = Conversation(user_id=db_user.id, title="Test")
    session.add(record)
    await session.flush()
    return record


def service_with(session, reader: ImageReader | None) -> DocumentService:
    return DocumentService(
        session, max_bytes=5 * 1024 * 1024, max_per_conversation=3, reader=reader
    )


async def test_an_uploaded_image_is_stored_as_its_transcript(session, db_user, conversation):
    reader = FakeReader("Invoice\nTotal: RM 1,240.00")
    document = await service_with(session, reader).add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="invoice.png",
        media_type="image/png",
        data=png(),
    )
    assert "RM 1,240.00" in document.text
    assert document.unit == "image"
    assert document.unit_count == 1
    assert document.token_count > 0


async def test_the_reader_is_handed_a_jpeg_not_the_original(session, db_user, conversation):
    """Preparation happens before the call, so the model never sees a 12MP PNG."""
    reader = FakeReader()
    await service_with(session, reader).add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="photo.png",
        media_type="image/png",
        data=png(),
    )
    assert [media for _, media in reader.calls] == ["image/jpeg"]


async def test_an_image_gets_a_thumbnail(session, db_user, conversation):
    document = await service_with(session, FakeReader()).add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="photo.png",
        media_type="image/png",
        data=png(),
    )
    assert document.thumbnail is not None
    assert document.thumbnail.startswith("data:image/jpeg;base64,")


async def test_a_text_file_gets_no_thumbnail(session, db_user, conversation):
    document = await service_with(session, FakeReader()).add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="notes.txt",
        media_type="text/plain",
        data=b"plain content",
    )
    assert document.thumbnail is None


async def test_without_a_reader_an_image_is_refused(session, db_user, conversation):
    with pytest.raises(ValidationError, match="no vision model is configured"):
        await service_with(session, None).add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="photo.png",
            media_type="image/png",
            data=png(),
        )


async def test_a_vision_failure_keeps_its_own_reason(session, db_user, conversation):
    """A rate limit and a bad key need different actions, and "could not read
    it" says neither."""
    reader = FailingReader(VisionError("The vision model is rate limited. Try again shortly."))
    with pytest.raises(ValidationError, match="rate limited"):
        await service_with(session, reader).add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="photo.png",
            media_type="image/png",
            data=png(),
        )


async def test_an_unexpected_vision_error_still_refuses_readably(
    session, db_user, conversation
):
    reader = FailingReader(RuntimeError("something odd"))
    with pytest.raises(ValidationError, match="could not be read"):
        await service_with(session, reader).add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="photo.png",
            media_type="image/png",
            data=png(),
        )


async def test_an_image_the_model_finds_nothing_in_is_refused(
    session, db_user, conversation
):
    """Storing an empty transcript would accept the upload and then answer
    every question about it with nothing."""
    with pytest.raises(ValidationError, match="Nothing readable"):
        await service_with(session, FakeReader("   ")).add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="blank.png",
            media_type="image/png",
            data=png(),
        )


async def test_a_corrupt_image_never_reaches_the_model(session, db_user, conversation):
    reader = FakeReader()
    with pytest.raises(ValidationError, match="could not be opened"):
        await service_with(session, reader).add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="broken.png",
            media_type="image/png",
            data=b"not a png",
        )
    assert reader.calls == []


async def test_an_image_counts_against_the_file_limit(session, db_user, conversation):
    """It is a file in the conversation like any other."""
    two = DocumentService(
        session, max_bytes=1024 * 1024, max_per_conversation=2, reader=FakeReader()
    )
    for name in ("one.png", "two.png"):
        await two.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename=name,
            media_type="image/png",
            data=png(),
        )
    with pytest.raises(ValidationError, match="which is the limit"):
        await two.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="three.png",
            media_type="image/png",
            data=png(),
        )
