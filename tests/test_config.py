import pytest

from config import Settings


def _settings_with_admin_ids(admin_ids):
    return Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS=admin_ids,
    )


def test_admin_ids_support_comma_separated_env_value() -> None:
    settings = _settings_with_admin_ids("111,222,333")

    assert settings.ADMIN_IDS == [111, 222, 333]


def test_admin_ids_support_space_and_semicolon_separated_env_value() -> None:
    settings = _settings_with_admin_ids("111 222;333")

    assert settings.ADMIN_IDS == [111, 222, 333]


def test_admin_ids_support_json_list_env_value() -> None:
    settings = _settings_with_admin_ids('[111, "222", 333]')

    assert settings.ADMIN_IDS == [111, 222, 333]


def test_admin_ids_reject_non_numeric_value() -> None:
    with pytest.raises(ValueError):
        _settings_with_admin_ids("111,not-id")


def test_rate_limit_backend_supports_memory_and_redis() -> None:
    memory_settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        RATE_LIMIT_BACKEND="memory",
    )
    redis_settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        RATE_LIMIT_BACKEND="redis",
    )

    assert memory_settings.RATE_LIMIT_BACKEND == "memory"
    assert redis_settings.RATE_LIMIT_BACKEND == "redis"


def test_rate_limit_backend_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            RATE_LIMIT_BACKEND="unknown",
        )


def test_tts_provider_supports_edge_and_gemini() -> None:
    edge_settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        TTS_PROVIDER="edge",
    )
    gemini_settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        TTS_PROVIDER="gemini",
    )

    assert edge_settings.TTS_PROVIDER == "edge"
    assert gemini_settings.TTS_PROVIDER == "gemini"


def test_tts_provider_supports_piper() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        TTS_PROVIDER="piper",
    )

    assert settings.TTS_PROVIDER == "piper"


def test_tts_provider_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            TTS_PROVIDER="unknown",
        )


def test_tts_provider_chain_supports_ordered_fallbacks() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        TTS_PROVIDER_CHAIN="gemini,piper,edge",
    )

    assert settings.TTS_PROVIDER_CHAIN == ["gemini", "piper", "edge"]


def test_tts_provider_chain_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            TTS_PROVIDER_CHAIN="gemini,unknown,edge",
        )


def test_ai_provider_chain_supports_ordered_fallbacks() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        AI_PROVIDER_CHAIN="ollama,gemini",
    )

    assert settings.AI_PROVIDER_CHAIN == ["ollama", "gemini"]


def test_gemini_model_chains_parse_unique_values() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        GEMINI_TEXT_MODEL_CHAIN="gemini-2.5-flash,gemini-3-flash-preview,gemini-2.5-flash",
        GEMINI_OCR_MODEL_CHAIN="gemini-2.5-flash-lite; gemini-2.5-flash",
        GEMINI_TTS_MODEL_CHAIN="gemini-2.5-flash-preview-tts",
    )

    assert settings.GEMINI_TEXT_MODEL_CHAIN == [
        "gemini-2.5-flash",
        "gemini-3-flash-preview",
    ]
    assert settings.GEMINI_OCR_MODEL_CHAIN == [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
    ]
    assert settings.GEMINI_TTS_MODEL_CHAIN == ["gemini-2.5-flash-preview-tts"]


def test_ai_provider_chain_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            AI_PROVIDER_CHAIN="ollama,unknown,gemini",
        )


def test_ocr_min_text_length_must_be_positive() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        OCR_MIN_TEXT_LENGTH=8,
    )

    assert settings.OCR_MIN_TEXT_LENGTH == 8


def test_ocr_min_text_length_rejects_zero() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            OCR_MIN_TEXT_LENGTH=0,
        )


def test_gemini_stability_settings_are_validated() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        GEMINI_REQUEST_TIMEOUT_SECONDS=20,
        GEMINI_RETRY_ATTEMPTS=3,
        GEMINI_RETRY_BASE_DELAY_SECONDS=0.5,
        GEMINI_RETRY_MAX_DELAY_SECONDS=2.0,
    )

    assert settings.GEMINI_REQUEST_TIMEOUT_SECONDS == 20
    assert settings.GEMINI_RETRY_ATTEMPTS == 3
    assert settings.GEMINI_RETRY_BASE_DELAY_SECONDS == 0.5
    assert settings.GEMINI_RETRY_MAX_DELAY_SECONDS == 2.0


def test_gemini_tts_chunk_max_length_is_validated() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        GEMINI_TTS_REQUEST_TIMEOUT_SECONDS=90,
        GEMINI_TTS_CHUNK_MAX_LENGTH=1200,
    )

    assert settings.GEMINI_TTS_REQUEST_TIMEOUT_SECONDS == 90
    assert settings.GEMINI_TTS_CHUNK_MAX_LENGTH == 1200

    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            GEMINI_TTS_CHUNK_MAX_LENGTH=0,
        )

    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            GEMINI_TTS_REQUEST_TIMEOUT_SECONDS=0,
        )


def test_gemini_retry_attempts_rejects_zero() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            GEMINI_RETRY_ATTEMPTS=0,
        )


def test_audio_cache_resource_settings_are_validated() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        AUDIO_CACHE_MAX_SIZE_MB=256,
        AUDIO_CACHE_MAX_AGE_DAYS=7,
        AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS=300,
    )

    assert settings.AUDIO_CACHE_MAX_SIZE_MB == 256
    assert settings.AUDIO_CACHE_MAX_AGE_DAYS == 7
    assert settings.AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS == 300


def test_export_audio_max_size_is_validated() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        EXPORT_AUDIO_MAX_SIZE_MB=32,
        EXPORT_AUDIO_CROSSFADE_MS=80,
    )

    assert settings.EXPORT_AUDIO_MAX_SIZE_MB == 32
    assert settings.EXPORT_AUDIO_SMOOTH_MERGE_ENABLED is True
    assert settings.EXPORT_AUDIO_CROSSFADE_MS == 80

    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            EXPORT_AUDIO_MAX_SIZE_MB=0,
        )

    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            EXPORT_AUDIO_CROSSFADE_MS=0,
        )
