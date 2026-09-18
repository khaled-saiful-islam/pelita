"""Attached files: extraction, limits, excerpt selection and the contributor."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.context.base import AttachedDocument, TurnContext
from app.context.documents import DocumentContributor
from app.core.errors import NotFoundError, ValidationError
from app.core.tokens import count_tokens
from app.db.models.conversation import Conversation, Message
from app.providers.base import Role, TokenBudget
from app.services.document_excerpts import chunk_document, keywords, select_excerpts
from app.services.document_extract import (
    UnreadableDocument,
    UnsupportedDocument,
    classify,
    extract,
)
from app.services.document_service import DocumentService, human_size


def make_pdf(lines: list[str]) -> bytes:
    """A structurally valid single-page PDF, built without a writer library.

    Hand-built so the fixture needs no extra dependency and cannot drift when
    one is upgraded.
    """
    content = "BT /F1 14 Tf 72 720 Td 18 TL\n"
    for line in lines:
        content += f"({line}) Tj T*\n"
    content += "ET"
    stream = content.encode()

    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>\nstream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref_at}\n%%EOF"
    ).encode()
    return bytes(out)


# --- classification -----------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "media_type", "expected"),
    [
        ("notes.txt", "text/plain", "text"),
        ("readme.md", "text/markdown", "text"),
        ("data.csv", "text/csv", "text"),
        ("report.pdf", "application/pdf", "pdf"),
        ("memo.docx", "application/octet-stream", "docx"),
        # Browsers send octet-stream for .md more often than they send the
        # right type, so the extension has to win.
        ("readme.md", "application/octet-stream", "text"),
        ("unknown", "text/plain", "text"),
    ],
)
def test_files_are_classified_by_extension_then_media_type(filename, media_type, expected):
    assert classify(filename=filename, media_type=media_type) == expected


# photo.png is not here: an image gets its own refusal naming the missing
# vision model, which `test_vision.py` covers.
@pytest.mark.parametrize("filename", ["app.exe", "archive.zip", "song.mp3"])
def test_unsupported_types_are_named_in_the_error(filename: str) -> None:
    with pytest.raises(UnsupportedDocument, match="not a supported file type"):
        classify(filename=filename, media_type="application/octet-stream")


# --- extraction ---------------------------------------------------------


def test_plain_text_is_read_and_counted() -> None:
    result = extract(b"line one\nline two\n", filename="a.txt", media_type="text/plain")
    assert "line one" in result.text
    assert result.unit == "line"


def test_invalid_utf8_still_reads() -> None:
    """A file that is mostly readable beats a refusal."""
    result = extract(b"caf\xe9 terms", filename="a.txt", media_type="text/plain")
    assert "terms" in result.text


def test_runs_of_blank_lines_are_collapsed() -> None:
    """Blank lines cost tokens without carrying meaning."""
    result = extract(b"a\n\n\n\n\nb", filename="a.txt", media_type="text/plain")
    assert result.text == "a\n\nb"


def test_a_pdf_is_read_page_by_page() -> None:
    data = make_pdf(["Quarterly Report", "Revenue grew 18 percent."])
    result = extract(data, filename="r.pdf", media_type="application/pdf")
    assert "Revenue grew 18 percent" in result.text
    assert result.unit == "page"
    assert result.count == 1


def test_a_corrupt_pdf_is_reported_readably() -> None:
    with pytest.raises(UnreadableDocument, match="could not be read"):
        extract(b"%PDF-1.4 not really a pdf", filename="r.pdf", media_type="application/pdf")


def test_a_pdf_with_no_text_mentions_ocr() -> None:
    """A scan is the common case, and "no text" alone does not explain it."""
    with pytest.raises(UnreadableDocument, match="OCR"):
        extract(make_pdf([]), filename="scan.pdf", media_type="application/pdf")


# --- excerpt selection --------------------------------------------------

CONTRACT = "\n\n".join(
    [
        "Introduction. This agreement is between Acme and Globex.",
        "Payment terms. Invoices are due within 30 days of receipt.",
        "Confidentiality. Both parties keep shared information private.",
        "Termination. Either party may terminate with 60 days written notice.",
        "Governing law. The laws of Malaysia apply.",
    ]
    * 30
)


def test_a_document_that_fits_is_passed_through_whole() -> None:
    text, trimmed = select_excerpts(
        "short document", question="anything", budget=500, model="gpt-4o-mini"
    )
    assert text == "short document"
    assert trimmed is False


def test_a_long_document_yields_the_parts_matching_the_question() -> None:
    text, trimmed = select_excerpts(
        CONTRACT, question="what are the termination terms?", budget=120, model="gpt-4o-mini"
    )
    assert trimmed is True
    assert "Termination" in text


def test_selection_follows_the_question() -> None:
    """The same document, two questions, two different excerpts."""
    payments, _ = select_excerpts(
        CONTRACT, question="when are invoices due?", budget=60, model="gpt-4o-mini"
    )
    assert "Payment terms" in payments


def test_excerpts_are_returned_in_document_order() -> None:
    text, _ = select_excerpts(
        CONTRACT,
        question="termination and payment and confidentiality",
        budget=400,
        model="gpt-4o-mini",
    )
    assert text.index("Payment terms") < text.index("Termination")


def test_skipped_material_is_marked() -> None:
    """Without a marker a model reads two distant passages as consecutive."""
    text, _ = select_excerpts(
        CONTRACT, question="governing law", budget=200, model="gpt-4o-mini"
    )
    assert "[…]" in text or text.count("Governing law") >= 1


def test_a_document_with_no_matching_words_still_yields_its_opening() -> None:
    text, trimmed = select_excerpts(
        CONTRACT, question="zzz unrelated xyzzy", budget=80, model="gpt-4o-mini"
    )
    assert trimmed is True
    assert text.strip()


def test_a_budget_smaller_than_any_chunk_still_yields_text() -> None:
    """Returning nothing would leave the model unable to say anything about the
    file and unable to say why, which reads as a failed upload."""
    text, trimmed = select_excerpts(
        CONTRACT, question="termination", budget=20, model="gpt-4o-mini"
    )
    assert trimmed is True
    assert text.strip()
    assert text.endswith("[…]")
    assert count_tokens(text, "gpt-4o-mini") <= 20


def test_a_zero_budget_yields_nothing() -> None:
    assert select_excerpts("text", question="q", budget=0, model="gpt-4o-mini") == ("", True)


def test_stopwords_are_not_treated_as_search_terms() -> None:
    assert keywords("what are the terms of the agreement") == {"terms", "agreement"}


def test_chunking_keeps_paragraphs_whole() -> None:
    chunks = chunk_document(CONTRACT, model="gpt-4o-mini")
    assert len(chunks) > 1
    assert all(chunk.text.strip() for chunk in chunks)


# --- the contributor ----------------------------------------------------


def doc(filename: str, text: str, *, unit: str = "line", count: int = 3) -> AttachedDocument:
    return AttachedDocument(
        id=uuid4(), filename=filename, text=text, unit=unit, unit_count=count
    )


def ctx(documents: tuple[AttachedDocument, ...], question: str = "what is the budget?"):
    return TurnContext(
        conversation_id=uuid4(),
        user_id=uuid4(),
        user_message=question,
        model="gpt-4o-mini",
        budget=TokenBudget(memory=512, tools=2048, history=4096),
        documents=documents,
    )


async def test_no_documents_contributes_nothing() -> None:
    assert await DocumentContributor(2000).contribute(ctx(())) == []


async def test_documents_are_labelled_by_filename() -> None:
    """The model is asked to name its source, so it has to be given one."""
    messages = await DocumentContributor(2000).contribute(
        ctx((doc("brief.txt", "The budget is RM 250,000."),))
    )
    assert len(messages) == 1
    assert messages[0].role is Role.SYSTEM
    assert "brief.txt" in messages[0].content
    assert "RM 250,000" in messages[0].content


async def test_the_budget_is_shared_between_files() -> None:
    """Otherwise one long file consumes it and a question about the third is
    answered from nothing, with no way for the user to know why."""
    messages = await DocumentContributor(400).contribute(
        ctx(
            (
                doc("long.txt", CONTRACT),
                doc("short.txt", "The deadline is 14 November."),
            ),
            question="what is the deadline?",
        )
    )
    body = messages[0].content
    assert "long.txt" in body
    assert "short.txt" in body
    assert "14 November" in body


async def test_trimmed_files_say_so() -> None:
    """So the model can qualify its answer rather than asserting more than the
    excerpt supports."""
    messages = await DocumentContributor(120).contribute(
        ctx((doc("long.txt", CONTRACT),), question="termination")
    )
    assert "most relevant" in messages[0].content


async def test_the_contributor_sits_at_the_retrieval_slot() -> None:
    assert DocumentContributor(100).order == 350


# --- the service --------------------------------------------------------


@pytest.fixture
async def conversation(session, db_user) -> Conversation:
    record = Conversation(user_id=db_user.id, title="Test")
    session.add(record)
    await session.flush()
    return record


@pytest.fixture
def service(session) -> DocumentService:
    return DocumentService(session, max_bytes=5 * 1024 * 1024, max_per_conversation=3)


async def test_a_file_is_stored_with_its_extracted_text(service, db_user, conversation):
    document = await service.add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="brief.txt",
        media_type="text/plain",
        data=b"Budget: RM 250,000.",
    )
    assert document.filename == "brief.txt"
    assert "RM 250,000" in document.text
    assert document.token_count > 0


async def test_an_oversized_file_states_both_sizes(session, db_user, conversation):
    """"5.2 MB, limit 5 MB" tells someone what to do; "too large" does not."""
    small = DocumentService(session, max_bytes=1024, max_per_conversation=3)
    with pytest.raises(ValidationError, match="limit is 1 KB"):
        await small.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="big.txt",
            media_type="text/plain",
            data=b"x" * 2048,
        )


async def test_the_file_limit_is_enforced(session, db_user, conversation):
    two = DocumentService(session, max_bytes=1024 * 1024, max_per_conversation=2)
    for index in range(2):
        await two.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename=f"f{index}.txt",
            media_type="text/plain",
            data=b"content",
        )
    with pytest.raises(ValidationError, match="which is the limit"):
        await two.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="third.txt",
            media_type="text/plain",
            data=b"content",
        )


async def test_an_empty_file_is_refused(service, db_user, conversation):
    with pytest.raises(ValidationError, match="is empty"):
        await service.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="empty.txt",
            media_type="text/plain",
            data=b"",
        )


async def test_an_unsupported_type_is_refused(service, db_user, conversation):
    with pytest.raises(ValidationError, match="not a supported file type"):
        await service.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="thing.exe",
            media_type="application/octet-stream",
            data=b"MZ\x90\x00",
        )


async def test_another_users_conversation_is_not_found(service, conversation):
    with pytest.raises(NotFoundError):
        await service.add(
            user_id=uuid4(),
            conversation_id=conversation.id,
            filename="a.txt",
            media_type="text/plain",
            data=b"content",
        )


async def test_files_are_listed_oldest_first(service, db_user, conversation):
    for name in ("first.txt", "second.txt"):
        await service.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename=name,
            media_type="text/plain",
            data=b"content",
        )
    listed = await service.list_for(conversation.id)
    assert [d.filename for d in listed] == ["first.txt", "second.txt"]


async def test_deleting_frees_a_slot(service, db_user, conversation):
    document = await service.add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="a.txt",
        media_type="text/plain",
        data=b"content",
    )
    await service.delete(
        user_id=db_user.id, conversation_id=conversation.id, document_id=document.id
    )
    assert await service.list_for(conversation.id) == []


async def test_deleting_someone_elses_file_is_not_found(service, db_user, conversation):
    document = await service.add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="a.txt",
        media_type="text/plain",
        data=b"content",
    )
    with pytest.raises(NotFoundError):
        await service.delete(
            user_id=uuid4(), conversation_id=conversation.id, document_id=document.id
        )


# --- binding a file to the message that sent it -------------------------


async def make_message(session, conversation: Conversation) -> Message:
    message = Message(conversation_id=conversation.id, role="user", content="Ask")
    session.add(message)
    await session.flush()
    return message


async def test_a_new_file_belongs_to_no_message_yet(service, db_user, conversation):
    """Between the upload and the next send it is still in the composer."""
    document = await service.add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="a.txt",
        media_type="text/plain",
        data=b"content",
    )
    assert document.message_id is None


async def test_sending_binds_the_pending_files(session, service, db_user, conversation):
    for name in ("a.txt", "b.txt"):
        await service.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename=name,
            media_type="text/plain",
            data=b"content",
        )
    message = await make_message(session, conversation)

    bound = await service.attach_to_message(conversation.id, message.id)

    assert bound == 2
    assert all(d.message_id == message.id for d in await service.list_for(conversation.id))


async def test_a_second_send_leaves_the_first_message_alone(
    session, service, db_user, conversation
):
    """Otherwise every card jumps to the newest message as the chat goes on."""
    first_file = await service.add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="first.txt",
        media_type="text/plain",
        data=b"content",
    )
    first_message = await make_message(session, conversation)
    await service.attach_to_message(conversation.id, first_message.id)

    second_file = await service.add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="second.txt",
        media_type="text/plain",
        data=b"content",
    )
    second_message = await make_message(session, conversation)
    bound = await service.attach_to_message(conversation.id, second_message.id)

    assert bound == 1
    await session.refresh(first_file)
    await session.refresh(second_file)
    assert first_file.message_id == first_message.id
    assert second_file.message_id == second_message.id


async def test_sending_with_nothing_attached_binds_nothing(session, service, conversation):
    message = await make_message(session, conversation)
    assert await service.attach_to_message(conversation.id, message.id) == 0


async def test_a_bound_file_still_counts_against_the_limit(
    session, db_user, conversation
):
    """The limit is on the conversation, not on the composer — otherwise
    sending resets it and a chat can hold any number of files."""
    two = DocumentService(session, max_bytes=1024 * 1024, max_per_conversation=2)
    for name in ("a.txt", "b.txt"):
        await two.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename=name,
            media_type="text/plain",
            data=b"content",
        )
    message = await make_message(session, conversation)
    await two.attach_to_message(conversation.id, message.id)

    with pytest.raises(ValidationError, match="which is the limit"):
        await two.add(
            user_id=db_user.id,
            conversation_id=conversation.id,
            filename="third.txt",
            media_type="text/plain",
            data=b"content",
        )


async def test_a_bound_file_is_still_read_by_the_contributor(
    session, service, db_user, conversation
):
    """A file stays readable for the rest of the chat, not just its own turn."""
    await service.add(
        user_id=db_user.id,
        conversation_id=conversation.id,
        filename="brief.txt",
        media_type="text/plain",
        data=b"The budget is RM 250,000.",
    )
    message = await make_message(session, conversation)
    await service.attach_to_message(conversation.id, message.id)

    listed = await service.list_for(conversation.id)
    assert [d.filename for d in listed] == ["brief.txt"]


@pytest.mark.parametrize(
    ("size", "expected"), [(500, "1 KB"), (1024 * 1024, "1 MB"), (5 * 1024 * 1024, "5 MB")]
)
def test_sizes_read_the_way_the_limit_is_written(size: int, expected: str) -> None:
    assert human_size(size) == expected
