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


def test_build_content_hash_normalizes_whitespace() -> None:
    first_hash = service.build_content_hash("  First   line.\nSecond line.  ")
    second_hash = service.build_content_hash("First line. Second line.")

    assert first_hash is not None
    assert first_hash == second_hash
    assert service.build_content_hash("Different text") != first_hash
    assert service.build_content_hash("  ") is None


def test_chunks_serialization_roundtrip() -> None:
    chunks = ["перший", "другий"]

    serialized = service.serialize_chunks(chunks)

    assert service.deserialize_chunks(serialized) == chunks


def test_voice_file_ids_serialization_roundtrip() -> None:
    file_ids = ["voice-1", "voice-2"]

    serialized = service.serialize_voice_file_ids(file_ids)

    assert service.deserialize_voice_file_ids(serialized) == file_ids
    assert service.deserialize_voice_file_ids(None) == []
    assert service.deserialize_voice_file_ids("{not json") == []


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
    assert captured["content_hash"] == service.build_content_hash("hello world")


@pytest.mark.asyncio
async def test_get_cached_summary_for_text(monkeypatch) -> None:
    captured = {}

    async def fake_get_latest_document_summary_by_content_hash(**kwargs):
        captured.update(kwargs)
        return {
            "summary_text": " Cached summary ",
            "summary_voice_file_ids_json": '["voice-1"]',
            "summary_voice_voice": "uk-UA-PolinaNeural",
            "summary_voice_rate": "+0%",
            "summary_voice_provider": "edge",
        }

    monkeypatch.setattr(
        service,
        "get_latest_document_summary_by_content_hash",
        fake_get_latest_document_summary_by_content_hash,
    )

    cached = await service.get_cached_summary_for_text(
        user_id=10,
        text="hello   world",
        chunks=["hello world"],
        exclude_document_id=42,
    )

    assert cached == service.CachedDocumentSummary(
        summary_text="Cached summary",
        summary_voice_file_ids=["voice-1"],
        summary_voice_voice="uk-UA-PolinaNeural",
        summary_voice_rate="+0%",
        summary_voice_provider="edge",
    )
    assert captured == {
        "user_id": 10,
        "content_hash": service.build_content_hash("hello world"),
        "exclude_document_id": 42,
    }


@pytest.mark.asyncio
async def test_get_cached_summary_for_text_falls_back_to_chunks(monkeypatch) -> None:
    calls = []

    async def fake_get_latest_document_summary_by_content_hash(**kwargs):
        calls.append(("content_hash", kwargs))
        return None

    async def fake_get_latest_document_summary_by_chunks_json(**kwargs):
        calls.append(("chunks_json", kwargs))
        return {
            "summary_text": "Cached summary",
            "summary_voice_file_ids_json": None,
            "summary_voice_voice": None,
            "summary_voice_rate": None,
            "summary_voice_provider": None,
        }

    monkeypatch.setattr(
        service,
        "get_latest_document_summary_by_content_hash",
        fake_get_latest_document_summary_by_content_hash,
    )
    monkeypatch.setattr(
        service,
        "get_latest_document_summary_by_chunks_json",
        fake_get_latest_document_summary_by_chunks_json,
    )

    cached = await service.get_cached_summary_for_text(
        user_id=10,
        text="hello world",
        chunks=["hello", "world"],
        exclude_document_id=42,
    )

    assert cached is not None
    assert cached.summary_text == "Cached summary"
    assert calls == [
        (
            "content_hash",
            {
                "user_id": 10,
                "content_hash": service.build_content_hash("hello world"),
                "exclude_document_id": 42,
            },
        ),
        (
            "chunks_json",
            {
                "user_id": 10,
                "chunks_json": service.serialize_chunks(["hello", "world"]),
                "exclude_document_id": 42,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_get_cached_summary_for_text_ignores_empty_cache(monkeypatch) -> None:
    async def fake_get_latest_document_summary_by_content_hash(**kwargs):
        return {
            "summary_text": "  ",
            "summary_voice_file_ids_json": None,
            "summary_voice_voice": None,
            "summary_voice_rate": None,
            "summary_voice_provider": None,
        }

    monkeypatch.setattr(
        service,
        "get_latest_document_summary_by_content_hash",
        fake_get_latest_document_summary_by_content_hash,
    )

    assert await service.get_cached_summary_for_text(
        user_id=10,
        text="hello",
    ) is None


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


@pytest.mark.asyncio
async def test_save_catalog_document_summary_audio(monkeypatch) -> None:
    captured = {}

    async def fake_set_document_summary_audio(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        service,
        "set_document_summary_audio",
        fake_set_document_summary_audio,
    )

    assert await service.save_catalog_document_summary_audio(
        user_id=1,
        document_id=2,
        voice_file_ids=[" voice-id "],
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        provider="edge",
    ) is True

    assert captured == {
        "user_id": 1,
        "document_id": 2,
        "voice_file_ids_json": '["voice-id"]',
        "voice": "uk-UA-PolinaNeural",
        "rate": "+0%",
        "provider": "edge",
    }

    assert await service.save_catalog_document_summary_audio(
        user_id=1,
        document_id=None,
        voice_file_ids=["voice-id"],
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        provider="edge",
    ) is False
    assert await service.save_catalog_document_summary_audio(
        user_id=1,
        document_id=2,
        voice_file_ids=[],
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        provider="edge",
    ) is False
