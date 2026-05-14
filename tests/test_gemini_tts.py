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
