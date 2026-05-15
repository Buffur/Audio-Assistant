from types import SimpleNamespace

import pytest

from services import gemini_tts


def _audio_response(data):
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(
                            inline_data=SimpleNamespace(data=data),
                        )
                    ]
                )
            )
        ]
    )


def test_rate_instruction_maps_supported_rates() -> None:
    assert gemini_tts._rate_instruction("-25%") == "Use a slightly slower pace."
    assert gemini_tts._rate_instruction("+25%") == "Use a slightly faster pace."
    assert gemini_tts._rate_instruction("+50%") == "Use a fast but still clear pace."
    assert gemini_tts._rate_instruction("+0%") == "Use a natural pace."


def test_get_gemini_tts_voice_uses_edge_voice_gender(monkeypatch) -> None:
    monkeypatch.setattr(gemini_tts, "GEMINI_TTS_FEMALE_VOICE", "Kore")
    monkeypatch.setattr(gemini_tts, "GEMINI_TTS_MALE_VOICE", "Charon")

    assert gemini_tts.get_gemini_tts_voice("uk-UA-PolinaNeural") == "Kore"
    assert gemini_tts.get_gemini_tts_voice("uk-UA-OstapNeural") == "Charon"
    assert gemini_tts.get_gemini_tts_voice("en-US-GuyNeural") == "Charon"


def test_gemini_tts_model_chain_uses_primary_and_fallbacks(monkeypatch) -> None:
    monkeypatch.setattr(gemini_tts, "GEMINI_TTS_MODEL", "gemini-primary-tts")
    monkeypatch.setattr(
        gemini_tts,
        "GEMINI_TTS_MODEL_CHAIN",
        ["gemini-fallback-tts", "gemini-primary-tts"],
    )

    assert gemini_tts.gemini_tts_model_chain() == [
        "gemini-primary-tts",
        "gemini-fallback-tts",
    ]


def test_extract_audio_data_supports_bytes() -> None:
    response = _audio_response(b"audio")

    assert gemini_tts._extract_audio_data(response) == b"audio"


def test_extract_audio_data_supports_base64_string() -> None:
    response = _audio_response("YXVkaW8=")

    assert gemini_tts._extract_audio_data(response) == b"audio"


def test_extract_audio_data_rejects_missing_payload() -> None:
    response = SimpleNamespace(candidates=[])

    with pytest.raises(RuntimeError):
        gemini_tts._extract_audio_data(response)


@pytest.mark.asyncio
async def test_generate_gemini_tts_uses_tts_timeout(monkeypatch) -> None:
    captured = {}

    async def fake_generate_gemini_content_with_fallback(**kwargs):
        captured.update(kwargs)
        return _audio_response(b"audio")

    async def fake_convert_to_ogg(wav_path):
        return "/tmp/audio.ogg"

    monkeypatch.setattr(
        gemini_tts,
        "GEMINI_TTS_REQUEST_TIMEOUT_SECONDS",
        123,
    )
    monkeypatch.setattr(
        gemini_tts,
        "generate_gemini_content_with_fallback",
        fake_generate_gemini_content_with_fallback,
    )
    monkeypatch.setattr(
        gemini_tts,
        "create_temp_file_path",
        lambda suffix: "/tmp/audio.wav",
    )
    monkeypatch.setattr(gemini_tts, "_write_pcm_to_wav", lambda **kwargs: None)
    monkeypatch.setattr(gemini_tts, "convert_to_ogg", fake_convert_to_ogg)
    monkeypatch.setattr(gemini_tts, "safe_remove_file", lambda path: None)

    result = await gemini_tts.generate_gemini_tts_ogg(
        text="hello",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        chunk_index=1,
        chunks_count=1,
    )

    assert result == "/tmp/audio.ogg"
    assert captured["context"] == "tts"
    assert captured["timeout_seconds"] == 123
