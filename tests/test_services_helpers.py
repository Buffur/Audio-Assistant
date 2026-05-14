from pathlib import Path

import pytest

from services import audio_cache
from services import content_extractor
from services import file_processor
from services import parser
from services import redis_client
from services import user_settings_service
from services import voice_selector


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
        "piper",
    ]
    assert user_settings_service.build_user_tts_provider_chain("piper") == [
        "piper",
        "edge",
    ]
    monkeypatch.setattr(
        user_settings_service,
        "is_piper_voice_configured",
        lambda voice: False,
    )
    assert user_settings_service.build_user_tts_provider_chain(
        "piper",
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
        "is_piper_voice_configured",
        lambda voice: True,
    )
    assert user_settings_service.build_user_tts_provider_chain(
        "piper",
        voice="en-US-JennyNeural",
    ) == ["piper", "edge"]
    assert user_settings_service.build_user_tts_provider_chain(
        "edge",
        voice="en-US-JennyNeural",
    ) == ["edge", "piper"]
    assert user_settings_service.build_user_tts_provider_chain(
        "gemini",
        voice="en-US-JennyNeural",
    ) == ["gemini", "edge", "piper"]

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
async def test_parser_ai_provider_chain_uses_ollama_first(monkeypatch) -> None:
    async def fake_ollama(prompt, temperature):
        fake_ollama.called_with = {
            "prompt": prompt,
            "temperature": temperature,
        }
        return "Локальний результат"

    async def fail_gemini(prompt, temperature):
        raise AssertionError("Gemini should not be called")

    monkeypatch.setattr(parser, "AI_PROVIDER_CHAIN", ["ollama", "gemini"])
    monkeypatch.setattr(parser, "_generate_text_with_ollama", fake_ollama)
    monkeypatch.setattr(parser, "_generate_text_with_gemini", fail_gemini)

    result = await parser._generate_ai_text("prompt", temperature=0.1)

    assert result == "Локальний результат"
    assert fake_ollama.called_with == {
        "prompt": "prompt",
        "temperature": 0.1,
    }


@pytest.mark.asyncio
async def test_parser_ai_provider_chain_falls_back_to_gemini(monkeypatch) -> None:
    async def fail_ollama(prompt, temperature):
        raise RuntimeError("Ollama is unavailable")

    async def fake_gemini(prompt, temperature):
        fake_gemini.called_with = {
            "prompt": prompt,
            "temperature": temperature,
        }
        return "Gemini результат"

    monkeypatch.setattr(parser, "AI_PROVIDER_CHAIN", ["ollama", "gemini"])
    monkeypatch.setattr(parser, "_generate_text_with_ollama", fail_ollama)
    monkeypatch.setattr(parser, "_generate_text_with_gemini", fake_gemini)

    result = await parser._generate_ai_text("prompt", temperature=0.2)

    assert result == "Gemini результат"
    assert fake_gemini.called_with == {
        "prompt": "prompt",
        "temperature": 0.2,
    }


def test_parser_content_type_helper() -> None:
    assert parser._is_supported_content_type("text/html; charset=utf-8") is True
    assert parser._is_supported_content_type("application/json") is False
    assert parser._is_supported_content_type("") is True


def test_content_extractor_detects_document_kind() -> None:
    assert content_extractor._detect_kind_by_magic_bytes(b"%PDF-1.7") == "pdf"
    assert content_extractor._detect_kind_by_magic_bytes(b"PK\x03\x04rest") == "docx"
    assert content_extractor._detect_kind_by_magic_bytes(b"\xff\xd8\xffrest") == "image"
    assert content_extractor._detect_kind_by_magic_bytes(b"\x89PNG\r\n\x1a\nrest") == "image"

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
