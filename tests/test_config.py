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


def test_reading_backends_support_memory_and_redis() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        READING_SESSION_BACKEND="memory",
        READING_GENERATION_STALE_SECONDS=120,
        READING_AUDIO_QUEUE_BACKEND="redis",
        READING_AUDIO_QUEUE_MAX_SIZE=5,
    )

    assert settings.READING_SESSION_BACKEND == "memory"
    assert settings.READING_GENERATION_STALE_SECONDS == 120
    assert settings.READING_AUDIO_QUEUE_BACKEND == "redis"
    assert settings.READING_AUDIO_QUEUE_MAX_SIZE == 5


def test_reading_generation_stale_seconds_rejects_zero() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            READING_GENERATION_STALE_SECONDS=0,
        )


def test_reading_generation_stale_seconds_must_be_lower_than_session_ttl() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            READING_SESSION_TTL_SECONDS=60,
            READING_GENERATION_STALE_SECONDS=60,
        )


def test_log_format_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            LOG_FORMAT="xml",
        )


def test_api_and_webhook_settings_are_validated() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        BOT_RUNTIME_MODE="webhook",
        API_ENABLED=True,
        API_PORT=9000,
        TELEGRAM_WEBHOOK_PATH="/telegram",
    )

    assert settings.BOT_RUNTIME_MODE == "webhook"
    assert settings.API_ENABLED is True
    assert settings.API_PORT == 9000
    assert settings.TELEGRAM_WEBHOOK_PATH == "/telegram"


def test_user_commands_are_hidden_by_default_but_configurable() -> None:
    default_settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
    )
    visible_settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        HIDE_USER_COMMANDS=False,
    )

    assert default_settings.HIDE_USER_COMMANDS is True
    assert visible_settings.HIDE_USER_COMMANDS is False
    assert default_settings.CLEAR_KNOWN_USER_COMMANDS_ON_STARTUP is False


def test_api_and_webhook_settings_reject_invalid_values() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            BOT_RUNTIME_MODE="api",
        )

    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            TELEGRAM_WEBHOOK_PATH="telegram",
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
        TTS_PROVIDER_CHAIN="gemini,edge",
    )

    assert settings.TTS_PROVIDER_CHAIN == ["gemini", "edge"]


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
        AI_PROVIDER_CHAIN="gemini",
    )

    assert settings.AI_PROVIDER_CHAIN == ["gemini"]


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


def test_default_gemini_model_chains_are_free_tier_fallbacks() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
    )

    expected_text_and_ocr_chain = [
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ]

    assert settings.GEMINI_TEXT_MODEL == "gemini-3.1-flash-lite"
    assert settings.GEMINI_TEXT_MODEL_CHAIN == expected_text_and_ocr_chain
    assert settings.GEMINI_OCR_MODEL == "gemini-3.1-flash-lite"
    assert settings.GEMINI_OCR_MODEL_CHAIN == expected_text_and_ocr_chain
    assert settings.GEMINI_TTS_MODEL == "gemini-3.1-flash-tts-preview"
    assert settings.GEMINI_TTS_MODEL_CHAIN == ["gemini-2.5-flash-preview-tts"]


def test_ai_provider_chain_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            AI_PROVIDER_CHAIN="removed-provider,gemini",
        )


def test_ocr_min_text_length_must_be_positive() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        OCR_MIN_TEXT_LENGTH=8,
        OCR_IMAGE_OPEN_TIMEOUT_SECONDS=5,
        OCR_TOTAL_TIMEOUT_SECONDS=100,
    )

    assert settings.OCR_MIN_TEXT_LENGTH == 8
    assert settings.OCR_IMAGE_OPEN_TIMEOUT_SECONDS == 5
    assert settings.OCR_TOTAL_TIMEOUT_SECONDS == 100


def test_ocr_min_text_length_rejects_zero() -> None:
    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            OCR_MIN_TEXT_LENGTH=0,
        )

    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            OCR_TOTAL_TIMEOUT_SECONDS=0,
        )


def test_file_processing_timeouts_are_validated() -> None:
    settings = Settings(
        BOT_TOKEN="123456:test_bot_token",
        GEMINI_API_KEY="test_gemini_api_key",
        ADMIN_IDS="111",
        TELEGRAM_FILE_DOWNLOAD_TIMEOUT_SECONDS=30,
        PDF_EXTRACTION_TIMEOUT_SECONDS=40,
        DOCX_EXTRACTION_TIMEOUT_SECONDS=35,
        TXT_EXTRACTION_TIMEOUT_SECONDS=10,
    )

    assert settings.TELEGRAM_FILE_DOWNLOAD_TIMEOUT_SECONDS == 30
    assert settings.PDF_EXTRACTION_TIMEOUT_SECONDS == 40
    assert settings.DOCX_EXTRACTION_TIMEOUT_SECONDS == 35
    assert settings.TXT_EXTRACTION_TIMEOUT_SECONDS == 10

    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            PDF_EXTRACTION_TIMEOUT_SECONDS=0,
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
        EDGE_TTS_REQUEST_TIMEOUT_SECONDS=80,
        GEMINI_TTS_REQUEST_TIMEOUT_SECONDS=90,
        GEMINI_TTS_CHUNK_MAX_LENGTH=1200,
    )

    assert settings.EDGE_TTS_REQUEST_TIMEOUT_SECONDS == 80
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

    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            EDGE_TTS_REQUEST_TIMEOUT_SECONDS=0,
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
        EXPORT_AUDIO_CONCAT_TIMEOUT_SECONDS=180,
    )

    assert settings.EXPORT_AUDIO_MAX_SIZE_MB == 32
    assert settings.EXPORT_AUDIO_SMOOTH_MERGE_ENABLED is True
    assert settings.EXPORT_AUDIO_CROSSFADE_MS == 80
    assert settings.EXPORT_AUDIO_CONCAT_TIMEOUT_SECONDS == 180

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

    with pytest.raises(ValueError):
        Settings(
            BOT_TOKEN="123456:test_bot_token",
            GEMINI_API_KEY="test_gemini_api_key",
            ADMIN_IDS="111",
            EXPORT_AUDIO_CONCAT_TIMEOUT_SECONDS=0,
        )
