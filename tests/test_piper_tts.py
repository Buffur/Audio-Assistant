from services import piper_tts


def test_rate_length_scale_maps_supported_rates() -> None:
    assert piper_tts._rate_length_scale("-25%") == 1.25
    assert piper_tts._rate_length_scale("+25%") == 0.85
    assert piper_tts._rate_length_scale("+50%") == 0.70
    assert piper_tts._rate_length_scale("+0%") == 1.0


def test_normalize_text_for_piper_lowercases_and_transliterates_latin() -> None:
    text = piper_tts._normalize_text_for_piper(
        "Привіт. Це тест Piper 2026 українською."
    )

    assert text == (
        "привіт. це тест піпер два нуль два шість українською."
    )


def test_normalize_text_for_piper_keeps_non_uk_latin() -> None:
    text = piper_tts._normalize_text_for_piper(
        "Hello Piper 2026.",
        language="en",
    )

    assert text == "hello piper 2026."


def test_build_piper_command_includes_optional_arguments(monkeypatch) -> None:
    monkeypatch.setattr(piper_tts, "PIPER_EXECUTABLE", "piper")
    monkeypatch.setattr(piper_tts, "_resolve_piper_executable", lambda: "piper")
    settings = piper_tts.PiperVoiceSettings(
        language="uk",
        model_path="/voices/uk.onnx",
        config_path="/voices/uk.json",
        speaker=2,
        length_scale=1.0,
    )

    command = piper_tts._build_piper_command(
        settings=settings,
        input_path="/tmp/input.txt",
        wav_path="/tmp/audio.wav",
        rate="+25%",
    )

    assert command == [
        "piper",
        "--model",
        "/voices/uk.onnx",
        "--input_file",
        "/tmp/input.txt",
        "--output_file",
        "/tmp/audio.wav",
        "--config",
        "/voices/uk.json",
        "--speaker",
        "2",
        "--length_scale",
        "0.85",
    ]


def test_is_piper_configured_requires_model_and_executable(
    monkeypatch,
    workspace_tmp_path,
) -> None:
    model_path = workspace_tmp_path / "uk.onnx"
    model_path.write_bytes(b"model")
    settings = piper_tts.PiperVoiceSettings(
        language="uk",
        model_path=str(model_path),
        config_path="",
        speaker=None,
        length_scale=1.0,
    )

    monkeypatch.setattr(piper_tts, "PIPER_EXECUTABLE", "piper")
    monkeypatch.setattr(piper_tts.shutil, "which", lambda executable: executable)

    assert piper_tts._is_piper_configured(settings)


def test_resolve_piper_path_falls_back_to_local_models_dir(
    monkeypatch,
    workspace_tmp_path,
) -> None:
    model_path = workspace_tmp_path / "data" / "piper" / "voice.onnx"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"model")

    monkeypatch.setattr(piper_tts, "BASE_DIR", workspace_tmp_path)
    monkeypatch.setattr(piper_tts, "PIPER_MODELS_DIR", "/app/data/piper")

    assert piper_tts._resolve_piper_path("voice.onnx") == str(model_path)


def test_get_piper_voice_settings_uses_language_model_directory(monkeypatch) -> None:
    monkeypatch.setattr(piper_tts, "PIPER_MODELS_DIR", "/voices")
    monkeypatch.setattr(piper_tts, "PIPER_LANGUAGE_MODELS_JSON", "")

    female_settings = piper_tts.get_piper_voice_settings("en-US-JennyNeural")
    male_settings = piper_tts.get_piper_voice_settings("en-US-GuyNeural")
    german_male_settings = piper_tts.get_piper_voice_settings("de-DE-ConradNeural")

    assert female_settings.language == "en"
    assert female_settings.model_path.endswith("en_US-amy-medium.onnx")
    assert female_settings.config_path.endswith("en_US-amy-medium.onnx.json")
    assert male_settings.language == "en"
    assert male_settings.model_path.endswith("en_US-ryan-medium.onnx")
    assert male_settings.config_path.endswith("en_US-ryan-medium.onnx.json")
    assert german_male_settings.language == "de"
    assert german_male_settings.model_path.endswith("de_DE-thorsten-medium.onnx")
    assert german_male_settings.config_path.endswith("de_DE-thorsten-medium.onnx.json")


def test_get_piper_voice_settings_uses_ukrainian_speakers(monkeypatch) -> None:
    monkeypatch.setattr(piper_tts, "PIPER_MODELS_DIR", "/voices")
    monkeypatch.setattr(piper_tts, "PIPER_MODEL_PATH", "")
    monkeypatch.setattr(piper_tts, "PIPER_CONFIG_PATH", "")
    monkeypatch.setattr(piper_tts, "PIPER_LANGUAGE_MODELS_JSON", "")

    female_settings = piper_tts.get_piper_voice_settings("uk-UA-PolinaNeural")
    male_settings = piper_tts.get_piper_voice_settings("uk-UA-OstapNeural")

    assert female_settings.speaker == 2
    assert male_settings.speaker == 1


def test_get_piper_voice_settings_returns_empty_for_missing_gender(
    monkeypatch,
) -> None:
    monkeypatch.setattr(piper_tts, "PIPER_MODELS_DIR", "/voices")
    monkeypatch.setattr(piper_tts, "PIPER_LANGUAGE_MODELS_JSON", "")

    settings = piper_tts.get_piper_voice_settings("cs-CZ-VlastaNeural")

    assert settings.language == "cs"
    assert settings.model_path == ""
    assert settings.config_path == ""
