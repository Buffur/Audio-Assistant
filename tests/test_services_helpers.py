import asyncio
from io import BytesIO
from pathlib import Path
import time
import zipfile

import pytest

from services import audio_cache
from services import content_extractor
from services import file_processor
from services import parser
from services import redis_client
from services import user_settings_service
from services import voice_selector
from services.operation_timeouts import OperationTimeoutError


def _build_zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)

    return buffer.getvalue()


def test_process_txt_supports_utf8_sig(workspace_tmp_path: Path) -> None:
    file_path = workspace_tmp_path / "text.txt"
    file_path.write_text("Привіт", encoding="utf-8-sig")

    assert file_processor.process_txt(str(file_path)) == "Привіт"


def test_process_txt_falls_back_to_cp1251(workspace_tmp_path: Path) -> None:
    file_path = workspace_tmp_path / "text.txt"
    file_path.write_bytes("Привіт".encode("cp1251"))

    assert file_processor.process_txt(str(file_path)) == "Привіт"


def test_process_pdf_stops_at_soft_limit(monkeypatch) -> None:
    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text
            self.calls = 0

        def get_text(self) -> str:
            self.calls += 1
            return self.text

    class FakeDocument:
        def __init__(self) -> None:
            self.first_page = FakePage("a" * (file_processor.PDF_TEXT_SOFT_LIMIT + 100))
            self.second_page = FakePage("should not be read")
            self.closed = False

        def __iter__(self):
            return iter([self.first_page, self.second_page])

        def close(self) -> None:
            self.closed = True

    fake_document = FakeDocument()
    monkeypatch.setattr(file_processor.fitz, "open", lambda file_path: fake_document)

    text = file_processor.process_pdf("fake.pdf")

    assert len(text) == file_processor.PDF_TEXT_SOFT_LIMIT
    assert fake_document.first_page.calls == 1
    assert fake_document.second_page.calls == 0
    assert fake_document.closed is True


@pytest.mark.asyncio
async def test_document_processor_timeout_is_explicit(monkeypatch) -> None:
    monkeypatch.setattr(content_extractor, "DOCX_EXTRACTION_TIMEOUT_SECONDS", 0.01)

    def slow_processor(file_path: str) -> str:
        time.sleep(0.05)
        return "too late"

    with pytest.raises(OperationTimeoutError) as error:
        await content_extractor._run_document_processor(
            slow_processor,
            "fake.docx",
            document_kind=content_extractor.DOCUMENT_KIND_DOCX,
        )

    assert error.value.operation == "docx_text_extraction"


@pytest.mark.asyncio
async def test_download_to_temp_file_timeout_is_explicit(monkeypatch) -> None:
    monkeypatch.setattr(
        content_extractor,
        "TELEGRAM_FILE_DOWNLOAD_TIMEOUT_SECONDS",
        0.01,
    )

    class FakeBot:
        async def download(self, telegram_file):
            await asyncio.sleep(0.05)
            return None

    message = type("FakeMessage", (), {"bot": FakeBot()})()

    with pytest.raises(OperationTimeoutError) as error:
        await content_extractor._download_to_temp_file(message, object())

    assert error.value.operation == "telegram_file_download"


@pytest.mark.asyncio
async def test_extract_from_document_returns_timeout_error(monkeypatch) -> None:
    fake_document = type(
        "FakeDocument",
        (),
        {
            "file_name": "book.pdf",
            "mime_type": "application/pdf",
            "file_size": 100,
        },
    )()
    fake_user = type("FakeUser", (), {"id": 123})()
    message = type(
        "FakeMessage",
        (),
        {
            "document": fake_document,
            "from_user": fake_user,
        },
    )()

    async def fake_download_to_temp_file(*args, **kwargs):
        return "fake.pdf", b"%PDF-1.7"

    async def fake_run_document_processor(*args, **kwargs):
        raise OperationTimeoutError("pdf_text_extraction", 0.01)

    monkeypatch.setattr(
        content_extractor,
        "_download_to_temp_file",
        fake_download_to_temp_file,
    )
    monkeypatch.setattr(
        content_extractor,
        "_run_document_processor",
        fake_run_document_processor,
    )
    monkeypatch.setattr(content_extractor, "_safe_remove_file", lambda path: None)

    result = await content_extractor._extract_from_document(message, None)

    assert result == content_extractor.FILE_PROCESSING_TIMEOUT_ERROR


def test_join_clean_text_blocks() -> None:
    assert file_processor._join_clean_text_blocks([" one ", "", " two "]) == "one\ntwo"


def test_voice_selector_uses_detected_language_and_preferred_gender(monkeypatch) -> None:
    monkeypatch.setattr(voice_selector, "detect", lambda text: "en")

    assert voice_selector.select_voice_for_text(
        "Hello world",
        "uk-UA-OstapNeural",
    ) == "en-US-GuyNeural"
    assert voice_selector.select_voice_for_text(
        "Hello world",
        "uk-UA-PolinaNeural",
    ) == "en-US-JennyNeural"


def test_voice_selector_falls_back_to_ukrainian_for_unsupported_language(monkeypatch) -> None:
    monkeypatch.setattr(voice_selector, "detect", lambda text: "fr")

    assert voice_selector.detect_text_language("Bonjour") == "uk"


def test_voice_selector_limits_language_detection_sample(monkeypatch) -> None:
    captured = {}

    def fake_detect(text):
        captured["text"] = text
        return "en"

    monkeypatch.setattr(voice_selector, "detect", fake_detect)

    long_text = "  " + "a" * (voice_selector.LANGUAGE_DETECTION_MAX_CHARS + 50)

    assert voice_selector.detect_text_language(long_text) == "en"
    assert len(captured["text"]) == voice_selector.LANGUAGE_DETECTION_MAX_CHARS


@pytest.mark.asyncio
async def test_user_settings_service_defaults_and_validation(monkeypatch) -> None:
    async def fake_get_user_settings(user_id):
        return None, None

    async def fake_set_user_settings(**kwargs):
        fake_set_user_settings.called_with = kwargs

    async def fake_get_user_tts_provider(user_id):
        return None

    async def fake_set_user_tts_provider(**kwargs):
        fake_set_user_tts_provider.called_with = kwargs

    async def fake_is_premium_user_false(user_id):
        return False

    async def fake_is_premium_user_true(user_id):
        return True

    monkeypatch.setattr(user_settings_service, "get_user_settings", fake_get_user_settings)
    monkeypatch.setattr(user_settings_service, "set_user_settings", fake_set_user_settings)
    monkeypatch.setattr(
        user_settings_service,
        "get_user_tts_provider",
        fake_get_user_tts_provider,
    )
    monkeypatch.setattr(
        user_settings_service,
        "set_user_tts_provider",
        fake_set_user_tts_provider,
    )
    monkeypatch.setattr(
        user_settings_service,
        "is_premium_user",
        fake_is_premium_user_false,
    )

    voice, rate = await user_settings_service.get_effective_user_settings(1)
    tts_provider = await user_settings_service.get_effective_user_tts_provider(1)

    assert voice == user_settings_service.DEFAULT_VOICE
    assert rate == user_settings_service.DEFAULT_RATE
    assert tts_provider == "edge"
    assert user_settings_service.build_user_tts_provider_chain("edge") == [
        "edge",
    ]
    assert user_settings_service.build_user_tts_provider_chain("removed-provider") == [
        "edge",
    ]
    assert user_settings_service.build_user_tts_provider_chain(
        "removed-provider",
        voice="en-US-JennyNeural",
    ) == ["edge"]
    assert user_settings_service.build_user_tts_provider_chain(
        "edge",
        voice="en-US-JennyNeural",
    ) == ["edge"]
    assert user_settings_service.build_user_tts_provider_chain(
        "gemini",
        voice="en-US-JennyNeural",
    ) == ["gemini", "edge"]

    monkeypatch.setattr(
        user_settings_service,
        "is_premium_user",
        fake_is_premium_user_true,
    )
    assert await user_settings_service.get_effective_user_tts_provider(1) == "gemini"

    await user_settings_service.update_user_rate(1, "+25%")
    assert fake_set_user_settings.called_with == {"user_id": 1, "rate": "+25%"}

    await user_settings_service.update_user_tts_provider(1, "edge")
    assert fake_set_user_tts_provider.called_with == {
        "user_id": 1,
        "tts_provider": "edge",
    }

    with pytest.raises(ValueError):
        await user_settings_service.update_user_voice(1, "")

    with pytest.raises(ValueError):
        await user_settings_service.update_user_rate(1, "+999%")

    with pytest.raises(ValueError):
        await user_settings_service.update_user_tts_provider(1, "gemini")


def test_parser_url_and_text_helpers() -> None:
    assert parser.extract_first_url("Читай https://example.com/news.") == "https://example.com/news"
    assert parser.extract_first_url("без посилання") is None

    assert parser._is_valid_url("https://example.com") is True
    assert parser._is_valid_url("ftp://example.com") is False
    assert parser._is_valid_url("https://user:pass@example.com") is False

    assert parser._is_private_ip("127.0.0.1") is True
    assert parser._is_private_ip("8.8.8.8") is False

    assert parser.clean_text_for_tts("Текст https://www.example.com/a/b") == "Текст example.com"
    assert parser._strip_ai_output("```text\nОсь текст статті: Новина\n```") == "Новина"


@pytest.mark.asyncio
async def test_parser_ai_provider_chain_ignores_removed_provider(monkeypatch) -> None:
    async def fake_gemini(prompt, temperature):
        fake_gemini.called_with = {
            "prompt": prompt,
            "temperature": temperature,
        }
        return "Локальний результат"

    monkeypatch.setattr(parser, "AI_PROVIDER_CHAIN", ["removed-provider", "gemini"])
    monkeypatch.setattr(parser, "_generate_text_with_gemini", fake_gemini)

    result = await parser._generate_ai_text("prompt", temperature=0.1)

    assert result == "Локальний результат"
    assert fake_gemini.called_with == {
        "prompt": "prompt",
        "temperature": 0.1,
    }


@pytest.mark.asyncio
async def test_parser_ai_provider_chain_uses_gemini(monkeypatch) -> None:
    async def fake_gemini(prompt, temperature):
        fake_gemini.called_with = {
            "prompt": prompt,
            "temperature": temperature,
        }
        return "Gemini результат"

    monkeypatch.setattr(parser, "AI_PROVIDER_CHAIN", ["gemini"])
    monkeypatch.setattr(parser, "_generate_text_with_gemini", fake_gemini)

    result = await parser._generate_ai_text("prompt", temperature=0.2)

    assert result == "Gemini результат"
    assert fake_gemini.called_with == {
        "prompt": "prompt",
        "temperature": 0.2,
    }


@pytest.mark.asyncio
async def test_summary_prompt_asks_ai_to_keep_input_language(monkeypatch) -> None:
    captured = {}

    async def fake_generate_ai_text(prompt, temperature):
        captured["prompt"] = prompt
        captured["temperature"] = temperature
        return "summary"

    monkeypatch.setattr(parser, "_generate_ai_text", fake_generate_ai_text)

    result = await parser.summarize_text_with_ai("English source text. " * 10)

    assert result == "summary"
    assert "Автоматично визнач мову" in captured["prompt"]
    assert "відповідай тією самою мовою" in captured["prompt"]


@pytest.mark.asyncio
async def test_large_summary_uses_part_summaries_before_final_summary(
    monkeypatch,
) -> None:
    prompts = []

    async def fake_generate_ai_text(prompt, temperature):
        prompts.append(prompt)

        if "КОРОТКІ ЗМІСТИ ЧАСТИН" in prompt:
            return "final summary"

        return f"partial summary {len(prompts)}"

    monkeypatch.setattr(parser, "_generate_ai_text", fake_generate_ai_text)
    monkeypatch.setattr(
        parser,
        "split_text",
        lambda text, max_length: [
            "first part " * 10,
            "second part " * 10,
            "third part " * 10,
        ],
    )

    result = await parser.summarize_text_with_ai("large source text " * 4000)

    assert result == "final summary"
    assert len(prompts) == 4
    assert "Це частина 1 з 3" in prompts[0]
    assert "Це частина 3 з 3" in prompts[2]
    assert "partial summary 1" in prompts[3]
    assert "partial summary 3" in prompts[3]


def test_parser_content_type_helper() -> None:
    assert parser._is_supported_content_type("text/html; charset=utf-8") is True
    assert parser._is_supported_content_type("application/json") is False
    assert parser._is_supported_content_type("") is True


def test_content_extractor_detects_document_kind() -> None:
    docx_bytes = _build_zip_bytes(
        {
            "[Content_Types].xml": b"<Types />",
            "word/document.xml": b"<w:document />",
        }
    )
    pptx_bytes = _build_zip_bytes(
        {
            "[Content_Types].xml": b"<Types />",
            "ppt/presentation.xml": b"<p:presentation />",
        }
    )

    assert content_extractor._detect_kind_by_magic_bytes(b"%PDF-1.7") == "pdf"
    assert content_extractor._detect_kind_by_magic_bytes(docx_bytes) == "docx"
    assert content_extractor._detect_kind_by_magic_bytes(pptx_bytes) is None
    assert content_extractor._detect_kind_by_magic_bytes(b"PK\x03\x04rest") is None
    assert content_extractor._detect_kind_by_magic_bytes(b"\xff\xd8\xffrest") == "image"
    assert content_extractor._detect_kind_by_magic_bytes(b"\x89PNG\r\n\x1a\nrest") == "image"

    assert content_extractor._detect_document_kind(
        filename="slides.pptx",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        file_bytes=pptx_bytes,
    ) is None
    assert content_extractor._detect_document_kind(
        filename="renamed.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_bytes=pptx_bytes,
    ) is None
    assert content_extractor._detect_document_kind(
        filename="notes.md",
        mime_type="text/plain",
        file_bytes=b"# notes",
    ) is None
    assert content_extractor._detect_document_kind(
        filename="note.txt",
        mime_type="",
        file_bytes="Привіт".encode("utf-8"),
    ) == "txt"
    assert content_extractor._detect_document_kind(
        filename="bad.txt",
        mime_type="",
        file_bytes=b"\x00\x00\x00",
    ) is None


def test_content_extractor_supported_document_metadata_is_strict() -> None:
    assert content_extractor.is_supported_document_metadata(
        type("Document", (), {"file_name": "book.docx", "mime_type": ""})()
    ) is True
    assert content_extractor.is_supported_document_metadata(
        type(
            "Document",
            (),
            {
                "file_name": "slides.pptx",
                "mime_type": (
                    "application/vnd.openxmlformats-officedocument."
                    "presentationml.presentation"
                ),
            },
        )()
    ) is False
    assert content_extractor.is_supported_document_metadata(
        type("Document", (), {"file_name": "notes.md", "mime_type": "text/plain"})()
    ) is False
    assert content_extractor.is_supported_document_metadata(
        type("Document", (), {"file_name": "", "mime_type": "text/plain"})()
    ) is True


def test_audio_cache_roundtrip(workspace_tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_ENABLED", True)
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_DIR", str(workspace_tmp_path))

    source_path = workspace_tmp_path / "source.ogg"
    source_path.write_bytes(b"voice")

    audio_cache.save_audio_to_cache(
        text="hello",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        audio_path=str(source_path),
    )

    cached_copy = audio_cache.get_audio_from_cache(
        text="hello",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
    )

    assert cached_copy is not None
    assert Path(cached_copy).read_bytes() == b"voice"
    Path(cached_copy).unlink()


def test_audio_cache_tracks_owners_and_deletes_only_unshared_cache(
    workspace_tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_ENABLED", True)
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_DIR", str(workspace_tmp_path))

    source_path = workspace_tmp_path / "source.ogg"
    source_path.write_bytes(b"voice")

    audio_cache.save_audio_to_cache(
        text="shared",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        audio_path=str(source_path),
        user_id=1,
    )
    audio_cache.save_audio_to_cache(
        text="shared",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        audio_path=str(source_path),
        user_id=2,
    )

    cache_key = audio_cache.build_audio_cache_key(
        "shared",
        "uk-UA-PolinaNeural",
        "+0%",
    )
    cached_path = audio_cache.get_cached_audio_path(cache_key)

    first_result = audio_cache.delete_user_audio_cache(1)

    assert first_result["owner_links_removed"] == 1
    assert first_result["removed_files"] == 0
    assert cached_path.exists()

    second_result = audio_cache.delete_user_audio_cache(2)

    assert second_result["owner_links_removed"] == 1
    assert second_result["removed_files"] == 1
    assert not cached_path.exists()
    assert not audio_cache.get_audio_cache_owner_path(cache_key).exists()


def test_audio_cache_hit_registers_owner(
    workspace_tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_ENABLED", True)
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_DIR", str(workspace_tmp_path))

    source_path = workspace_tmp_path / "source.ogg"
    source_path.write_bytes(b"voice")

    audio_cache.save_audio_to_cache(
        text="hit",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        audio_path=str(source_path),
        user_id=1,
    )

    cached_copy = audio_cache.get_audio_from_cache(
        text="hit",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        user_id=2,
    )

    assert cached_copy is not None
    Path(cached_copy).unlink()

    first_result = audio_cache.delete_user_audio_cache(1)
    second_result = audio_cache.delete_user_audio_cache(2)

    assert first_result["removed_files"] == 0
    assert second_result["removed_files"] == 1


def test_user_audio_cache_delete_ignores_legacy_unowned_cache(
    workspace_tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_ENABLED", True)
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_DIR", str(workspace_tmp_path))

    cache_key = audio_cache.build_audio_cache_key(
        "legacy",
        "uk-UA-PolinaNeural",
        "+0%",
    )
    cached_path = audio_cache.get_cached_audio_path(cache_key)
    cached_path.write_bytes(b"legacy")

    result = audio_cache.delete_user_audio_cache(1)

    assert result == {
        "removed_files": 0,
        "removed_bytes": 0,
        "owner_links_removed": 0,
    }
    assert cached_path.exists()


def test_audio_cache_cleanup_removes_old_and_oversized_files(
    workspace_tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_ENABLED", True)
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_DIR", str(workspace_tmp_path))
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_MAX_AGE_DAYS", 1)
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_MAX_SIZE_MB", 1)

    now = 1_000_000.0
    old_file = workspace_tmp_path / "old.ogg"
    larger_old_file = workspace_tmp_path / "larger-old.ogg"
    larger_new_file = workspace_tmp_path / "larger-new.ogg"

    old_file.write_bytes(b"old")
    larger_old_file.write_bytes(b"a" * (800 * 1024))
    larger_new_file.write_bytes(b"b" * (800 * 1024))

    old_time = now - (2 * audio_cache.SECONDS_IN_DAY)
    larger_old_time = now - 300
    larger_new_time = now - 100

    old_file.touch()
    larger_old_file.touch()
    larger_new_file.touch()

    import os

    os.utime(old_file, (old_time, old_time))
    os.utime(larger_old_file, (larger_old_time, larger_old_time))
    os.utime(larger_new_file, (larger_new_time, larger_new_time))

    result = audio_cache.cleanup_audio_cache(now=now)

    assert result["removed_files"] == 2
    assert not old_file.exists()
    assert not larger_old_file.exists()
    assert larger_new_file.exists()
    assert result["remaining_bytes"] == 800 * 1024


def test_audio_cache_cleanup_interval(workspace_tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_ENABLED", True)
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_DIR", str(workspace_tmp_path))
    monkeypatch.setattr(audio_cache, "AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS", 60)
    monkeypatch.setattr(audio_cache, "_last_cleanup_time", 100.0)

    assert audio_cache.maybe_cleanup_audio_cache(now=120.0) is None
    assert audio_cache.maybe_cleanup_audio_cache(now=161.0) is not None


def test_redis_url_redaction() -> None:
    assert redis_client._redact_redis_url("redis://localhost:6379/0") == "redis://localhost:6379/0"
    assert (
        redis_client._redact_redis_url("redis://user:secret@example.com:6379/0")
        == "redis://user:***@example.com:6379/0"
    )
