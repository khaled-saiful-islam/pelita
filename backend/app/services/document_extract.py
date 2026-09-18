"""Getting text out of an uploaded file.

Three formats, one function each, and a dispatcher that picks by media type
with the filename as a fallback — browsers disagree about the type of a .md or
.docx, and guessing from the extension is more reliable than trusting them.

Extraction failures are reported with a message a person can act on. "Could not
read that PDF" tells someone to try a different export; a stack trace does not.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Media types and extensions accepted at the door.
TEXT_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/x-markdown",
        "application/json",
        "application/xml",
        "text/xml",
    }
)
PDF_TYPES = frozenset({"application/pdf"})
DOCX_TYPES = frozenset(
    {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
)

TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".log", ".rst")
PDF_SUFFIXES = (".pdf",)
DOCX_SUFFIXES = (".docx",)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic", ".heif")

SUPPORTED_DESCRIPTION = "plain text, Markdown, CSV, JSON, PDF or Word (.docx)"
SUPPORTED_WITH_IMAGES = f"{SUPPORTED_DESCRIPTION}, or an image"


def supported_description(*, images: bool) -> str:
    """What to tell someone they may upload. Depends on whether a vision model
    is configured, because promising images without one is worse than refusing
    them."""
    return SUPPORTED_WITH_IMAGES if images else SUPPORTED_DESCRIPTION


class UnsupportedDocument(ValueError):
    """The file is not a kind we can read, with a message safe to show."""


class UnreadableDocument(ValueError):
    """The file is a supported kind but could not be read."""


@dataclass(frozen=True, slots=True)
class ExtractedText:
    text: str
    # Pages for a PDF, paragraphs for a docx, lines for text. Shown in the UI so
    # someone can tell a 2-page memo from a 400-page report at a glance.
    unit: str
    count: int


def extract(data: bytes, *, filename: str, media_type: str) -> ExtractedText:
    """Read a file into text, or say why it could not be read.

    Images are not handled here: reading one is a network call, and this stays
    a pure function so it can be tested without one. `DocumentService` routes
    them to the image reader.
    """
    kind = classify(filename=filename, media_type=media_type)
    if kind == "pdf":
        return _from_pdf(data)
    if kind == "docx":
        return _from_docx(data)
    return _from_text(data)


def classify(*, filename: str, media_type: str, images: bool = False) -> str:
    """Return 'text', 'pdf', 'docx' or 'image'.

    Extension first: browsers send `application/octet-stream` for .md and
    sometimes for .docx, so the name is the more reliable signal.

    `images` says whether a vision model is configured. Without one an image is
    refused here rather than accepted and stored unreadable — a file that
    uploads cleanly and then cannot be asked about is the worse failure.
    """
    lowered = filename.lower()
    base = media_type.split(";")[0].strip().lower()

    if lowered.endswith(PDF_SUFFIXES):
        return "pdf"
    if lowered.endswith(DOCX_SUFFIXES):
        return "docx"
    if lowered.endswith(IMAGE_SUFFIXES) or base.startswith("image/"):
        if not images:
            raise UnsupportedDocument(
                f"{filename} is an image, and no vision model is configured. "
                f"Upload {SUPPORTED_DESCRIPTION}."
            )
        return "image"
    if lowered.endswith(TEXT_SUFFIXES):
        return "text"

    if base in PDF_TYPES:
        return "pdf"
    if base in DOCX_TYPES:
        return "docx"
    if base in TEXT_TYPES or base.startswith("text/"):
        return "text"

    raise UnsupportedDocument(
        f"{filename} is not a supported file type. "
        f"Upload {supported_description(images=images)}."
    )


def _from_text(data: bytes) -> ExtractedText:
    # utf-8 first, then latin-1, which cannot fail — a file that is mostly
    # readable with a few odd bytes is more useful than a refusal.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")
    cleaned = _normalise(text)
    return ExtractedText(text=cleaned, unit="line", count=cleaned.count("\n") + 1)


def _from_pdf(data: bytes) -> ExtractedText:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # An empty password unlocks many "protected" PDFs; a real one does
            # not, and that is a refusal the user can act on.
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001 - any failure means locked
                raise UnreadableDocument(
                    "That PDF is password protected. Remove the password and try again."
                ) from exc
        pages = [page.extract_text() or "" for page in reader.pages]
    except UnreadableDocument:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises a wide family, and
        # the exception names have moved between major versions; what matters is
        # that any failure becomes a message someone can act on.
        logger.info("could not read pdf: %s", exc)
        raise UnreadableDocument(
            "That PDF could not be read. It may be corrupt or an unusual format."
        ) from exc

    text = _normalise("\n\n".join(pages))
    if not text.strip():
        raise UnreadableDocument(
            "No text found in that PDF. Scanned documents need OCR before they can be read."
        )
    return ExtractedText(text=text, unit="page", count=len(pages))


def _from_docx(data: bytes) -> ExtractedText:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        # Tables hold a lot of the content in real documents and are not
        # paragraphs, so they are read separately rather than lost.
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
    except Exception as exc:  # noqa: BLE001 - python-docx raises broadly
        logger.info("could not read docx: %s", exc)
        raise UnreadableDocument(
            "That Word file could not be read. Try saving it again as .docx."
        ) from exc

    text = _normalise("\n".join(parts))
    if not text.strip():
        raise UnreadableDocument("That Word file appears to be empty.")
    return ExtractedText(text=text, unit="paragraph", count=len(parts))


def _normalise(text: str) -> str:
    """Normalise line endings and collapse runs of blank lines.

    Extractors emit a lot of vertical whitespace, and blank lines cost tokens
    without carrying meaning.
    """
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out: list[str] = []
    blanks = 0
    for line in lines:
        if line:
            blanks = 0
            out.append(line)
        else:
            blanks += 1
            if blanks <= 1:
                out.append("")
    return "\n".join(out).strip()
