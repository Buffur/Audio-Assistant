from types import SimpleNamespace

import pytest

from services import document_history_service as service


def _message(
    *,
    text=None,
    document=None,
    photo=None,
):
    return SimpleNamespace(text=text, document=document, photo=photo)


def test_detect_message_source_type() -> None:
    document = SimpleNamespace(file_name="book.pdf")

    assert service.detect_message_source_type(_message(document=document)) == "document"
    assert service.detect_message_source_type(_message(photo=[object()])) == "photo"
    assert service.detect_message_source_type(_message(text="https://example.com")) == "url"
    assert service.detect_message_source_type(_message(text="plain text")) == "text"
    assert service.detect_message_source_type(_message()) == "unknown"


def test_get_message_source_name() -> None:
    document = SimpleNamespace(file_name="book.pdf")
    nameless_document = SimpleNamespace(file_name=None)

    assert service.get_message_source_name(_message(document=document)) == "book.pdf"
    assert service.get_message_source_name(_message(document=nameless_document)) == "Документ без назви"
    assert service.get_message_source_name(_message(photo=[object()])) == "Фото з текстом"
    assert service.get_message_source_name(_message(text="https://example.com")) == "Посилання"
    assert service.get_message_source_name(_message(text="plain text")) == "Текстове повідомлення"
    assert service.get_message_source_name(_message()) == "Невідоме джерело"


def test_build_text_preview_collapses_whitespace_and_truncates() -> None:
    text = "  Перше   речення.\n\nДруге речення.  "
    assert service.build_text_preview(text) == "Перше речення. Друге речення."

    long_text = "а" * (service.TEXT_PREVIEW_LENGTH + 20)
    preview = service.build_text_preview(long_text)

    assert len(preview) == service.TEXT_PREVIEW_LENGTH
    assert preview.endswith("...")


def test_chunks_serialization_roundtrip() -> None:
    chunks = ["перший", "другий"]

    serialized = service.serialize_chunks(chunks)

    assert service.deserialize_chunks(serialized) == chunks


def test_deserialize_chunks_handles_bad_payloads() -> None:
    assert service.deserialize_chunks(None) == []
    assert service.deserialize_chunks("") == []
    assert service.deserialize_chunks("{not json") == []
    assert service.deserialize_chunks('{"not": "list"}') == []
    assert service.deserialize_chunks('["ok", "", "  ", 123]') == ["ok", "123"]


@pytest.mark.asyncio
async def test_save_document_history_from_message(monkeypatch) -> None:
    captured = {}

    async def fake_add_document_history(**kwargs):
        captured.update(kwargs)
        return 42

    monkeypatch.setattr(service, "add_document_history", fake_add_document_history)

    document_id = await service.save_document_history_from_message(
        user_id=10,
        message=_message(text="hello"),
        text="hello world",
        chunks=["hello", "world"],
    )

    assert document_id == 42
    assert captured["user_id"] == 10
    assert captured["source_type"] == "text"
    assert captured["source_name"] == "Текстове повідомлення"
    assert captured["chunks_count"] == 2


@pytest.mark.asyncio
async def test_save_document_history_skips_empty_text_or_chunks(monkeypatch) -> None:
    async def fake_add_document_history(**kwargs):
        raise AssertionError("add_document_history should not be called")

    monkeypatch.setattr(service, "add_document_history", fake_add_document_history)

    assert await service.save_document_history_from_message(
        user_id=10,
        message=_message(text="hello"),
        text="",
        chunks=["hello"],
    ) is None


@pytest.mark.asyncio
async def test_save_catalog_document_summary(monkeypatch) -> None:
    captured = {}

    async def fake_set_document_summary(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(service, "set_document_summary", fake_set_document_summary)

    assert await service.save_catalog_document_summary(
        user_id=1,
        document_id=2,
        summary_text=" Summary ",
    ) is True
    assert captured == {
        "user_id": 1,
        "document_id": 2,
        "summary_text": "Summary",
    }

    assert await service.save_catalog_document_summary(
        user_id=1,
        document_id=None,
        summary_text="Summary",
    ) is False
    assert await service.save_document_history_from_message(
        user_id=10,
        message=_message(text="hello"),
        text="hello",
        chunks=[],
    ) is None
