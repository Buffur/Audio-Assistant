# Файл: config.py

import json
import re
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    BOT_TOKEN: str
    GEMINI_API_KEY: str

    DEFAULT_VOICE: str = "uk-UA-PolinaNeural"
    DEFAULT_RATE: str = "+0%"

    AI_PROVIDER_CHAIN: Annotated[list[str], NoDecode] = Field(default_factory=list)
    GEMINI_TEXT_MODEL: str = "gemini-3.1-flash-lite"
    GEMINI_TEXT_MODEL_CHAIN: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "gemini-3.5-flash",
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ]
    )
    GEMINI_REQUEST_TIMEOUT_SECONDS: int = 45
    GEMINI_RETRY_ATTEMPTS: int = 2
    GEMINI_RETRY_BASE_DELAY_SECONDS: float = 1.0
    GEMINI_RETRY_MAX_DELAY_SECONDS: float = 6.0
    GEMINI_ESTIMATED_INPUT_COST_PER_1K_CHARS_USD: float = 0.0
    GEMINI_ESTIMATED_OUTPUT_COST_PER_1K_CHARS_USD: float = 0.0

    GEMINI_OCR_MODEL: str = "gemini-3.1-flash-lite"
    GEMINI_OCR_MODEL_CHAIN: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "gemini-3.5-flash",
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ]
    )
    OCR_MIN_TEXT_LENGTH: int = 12

    TTS_PROVIDER: str = "edge"
    TTS_PROVIDER_CHAIN: Annotated[list[str], NoDecode] = Field(default_factory=list)
    TTS_ESTIMATED_COST_PER_1K_CHARS_USD: float = 0.0
    EDGE_TTS_REQUEST_TIMEOUT_SECONDS: int = 90
    GEMINI_TTS_MODEL: str = "gemini-3.1-flash-tts-preview"
    GEMINI_TTS_MODEL_CHAIN: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["gemini-2.5-flash-preview-tts"]
    )
    GEMINI_TTS_VOICE: str = "Kore"
    GEMINI_TTS_FEMALE_VOICE: str = "Kore"
    GEMINI_TTS_MALE_VOICE: str = "Charon"
    GEMINI_TTS_STYLE_PROMPT: str = (
        "Detect the language of the input text automatically and read it clearly "
        "and naturally in the same language. "
        "Keep a calm, friendly pace and a consistent neutral newsroom tone. "
        "Treat every chunk as part of one continuous article."
    )
    GEMINI_TTS_REQUEST_TIMEOUT_SECONDS: int = 120
    GEMINI_TTS_CHUNK_MAX_LENGTH: int = 1600
    ADMIN_IDS: Annotated[list[int], NoDecode] = Field(default_factory=list)
    HIDE_USER_COMMANDS: bool = True
    CLEAR_KNOWN_USER_COMMANDS_ON_STARTUP: bool = False

    DB_PATH: str = "bot_database.sqlite"
    REDIS_URL: str = "redis://localhost:6379/0"
    DOCUMENT_HISTORY_RETENTION_DAYS: int = 90
    SERVICE_METRICS_RETENTION_DAYS: int = 30
    MAINTENANCE_CLEANUP_INTERVAL_SECONDS: int = 24 * 60 * 60

    RATE_LIMIT_MAX_EVENTS: int = 8
    RATE_LIMIT_PERIOD_SECONDS: int = 10
    RATE_LIMIT_WARNING_COOLDOWN_SECONDS: int = 10
    RATE_LIMIT_BACKEND: str = "memory"

    READING_SESSION_TTL_SECONDS: int = 45 * 60
    READING_SESSION_BACKEND: str = "redis"
    READING_AUDIO_QUEUE_BACKEND: str = "redis"
    READING_AUDIO_QUEUE_REDIS_KEY: str = "reading:audio:queue"
    READING_AUDIO_QUEUE_MAX_SIZE: int = 20
    EXPORT_AUDIO_MAX_SIZE_MB: int = 48
    EXPORT_AUDIO_SMOOTH_MERGE_ENABLED: bool = True
    EXPORT_AUDIO_CROSSFADE_MS: int = 120

    AUDIO_CACHE_ENABLED: bool = True
    AUDIO_CACHE_DIR: str = str(BASE_DIR / "data" / "audio_cache")
    AUDIO_CACHE_MAX_SIZE_MB: int = 1024
    AUDIO_CACHE_MAX_AGE_DAYS: int = 30
    AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS: int = 60 * 60

    FREE_DAILY_TEXT_MESSAGE_LIMIT: int = 100
    FREE_DAILY_FILE_LIMIT: int = 10
    FREE_DAILY_OCR_LIMIT: int = 10
    FREE_DAILY_LINK_LIMIT: int = 20
    FREE_DAILY_SUMMARY_LIMIT: int = 5

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"
    LOG_SERVICE_NAME: str = "audio-assistant"

    APP_VERSION: str = "0.1.0"
    BOT_RUNTIME_MODE: str = "polling"
    API_ENABLED: bool = False
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8080
    API_AUTH_TOKEN: str = ""
    TELEGRAM_WEBHOOK_URL: str = ""
    TELEGRAM_WEBHOOK_PATH: str = "/webhook/telegram"
    TELEGRAM_WEBHOOK_SECRET_TOKEN: str = ""

    METRICS_REDIS_STREAM_ENABLED: bool = False
    METRICS_REDIS_STREAM_KEY: str = "metrics:service"
    METRICS_REDIS_STREAM_MAXLEN: int = 10_000
    METRICS_ALERT_WEBHOOK_URL: str = ""
    METRICS_ALERT_ON_FAILURE: bool = True
    METRICS_ALERT_TIMEOUT_SECONDS: int = 5

    @field_validator("BOT_TOKEN", "GEMINI_API_KEY")
    @classmethod
    def _validate_required_string(cls, value: str, info: Any) -> str:
        value = value.strip()

        if not value:
            raise ValueError(f"{info.field_name} must not be empty")

        return value

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: Any) -> list[int]:
        if value is None:
            return []

        if isinstance(value, int):
            return [value]

        if isinstance(value, list):
            return [int(item) for item in value]

        if isinstance(value, tuple):
            return [int(item) for item in value]

        if isinstance(value, str):
            if not value.strip():
                return []

            admin_ids: list[int] = []
            value = value.strip()

            if value.startswith("["):
                try:
                    parsed_value = json.loads(value)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        "ADMIN_IDS JSON list is invalid. "
                        "Use [123,456] or 123,456."
                    ) from error

                if not isinstance(parsed_value, list):
                    raise ValueError(
                        "ADMIN_IDS JSON value must be a list of numeric Telegram user IDs"
                    )

                return [int(item) for item in parsed_value]

            for item in re.split(r"[\s,;]+", value):
                item = item.strip()

                if not item:
                    continue

                if not item.isdigit():
                    raise ValueError(
                        "ADMIN_IDS must contain only numeric Telegram user IDs "
                        "separated by commas"
                    )

                admin_ids.append(int(item))

            return admin_ids

        raise ValueError(
            "ADMIN_IDS must be an integer, a comma-separated string, "
            "or a list of integers"
        )

    @field_validator("ADMIN_IDS")
    @classmethod
    def _validate_admin_ids_not_empty(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError(
                "ADMIN_IDS is empty. Add at least one Telegram user ID to .env."
            )

        return value

    @field_validator(
        "RATE_LIMIT_MAX_EVENTS",
        "RATE_LIMIT_PERIOD_SECONDS",
        "RATE_LIMIT_WARNING_COOLDOWN_SECONDS",
        "READING_SESSION_TTL_SECONDS",
        "READING_AUDIO_QUEUE_MAX_SIZE",
        "EXPORT_AUDIO_MAX_SIZE_MB",
        "EXPORT_AUDIO_CROSSFADE_MS",
        "FREE_DAILY_TEXT_MESSAGE_LIMIT",
        "FREE_DAILY_FILE_LIMIT",
        "FREE_DAILY_OCR_LIMIT",
        "FREE_DAILY_LINK_LIMIT",
        "FREE_DAILY_SUMMARY_LIMIT",
        "GEMINI_REQUEST_TIMEOUT_SECONDS",
        "GEMINI_RETRY_ATTEMPTS",
        "EDGE_TTS_REQUEST_TIMEOUT_SECONDS",
        "OCR_MIN_TEXT_LENGTH",
        "GEMINI_TTS_REQUEST_TIMEOUT_SECONDS",
        "GEMINI_TTS_CHUNK_MAX_LENGTH",
        "DOCUMENT_HISTORY_RETENTION_DAYS",
        "SERVICE_METRICS_RETENTION_DAYS",
        "MAINTENANCE_CLEANUP_INTERVAL_SECONDS",
        "AUDIO_CACHE_MAX_SIZE_MB",
        "AUDIO_CACHE_MAX_AGE_DAYS",
        "AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS",
        "METRICS_REDIS_STREAM_MAXLEN",
        "METRICS_ALERT_TIMEOUT_SECONDS",
        "API_PORT",
    )
    @classmethod
    def _validate_positive_int(cls, value: int, info: Any) -> int:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")

        return value

    @field_validator(
        "GEMINI_ESTIMATED_INPUT_COST_PER_1K_CHARS_USD",
        "GEMINI_ESTIMATED_OUTPUT_COST_PER_1K_CHARS_USD",
        "TTS_ESTIMATED_COST_PER_1K_CHARS_USD",
    )
    @classmethod
    def _validate_non_negative_float(cls, value: float, info: Any) -> float:
        if value < 0:
            raise ValueError(f"{info.field_name} must not be negative")

        return value

    @field_validator("AI_PROVIDER_CHAIN", mode="before")
    @classmethod
    def _parse_ai_provider_chain(cls, value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            if not value.strip():
                return []

            providers = re.split(r"[\s,;]+", value.strip())

        elif isinstance(value, (list, tuple)):
            providers = [str(item) for item in value]

        else:
            raise ValueError(
                "AI_PROVIDER_CHAIN must be a comma-separated string or list"
            )

        normalized_providers: list[str] = []

        for provider in providers:
            provider = provider.strip().lower()

            if not provider:
                continue

            if provider not in {"gemini"}:
                raise ValueError(
                    "AI_PROVIDER_CHAIN must contain only gemini"
                )

            if provider not in normalized_providers:
                normalized_providers.append(provider)

        return normalized_providers

    @field_validator(
        "GEMINI_TEXT_MODEL_CHAIN",
        "GEMINI_OCR_MODEL_CHAIN",
        "GEMINI_TTS_MODEL_CHAIN",
        mode="before",
    )
    @classmethod
    def _parse_model_chain(cls, value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            if not value.strip():
                return []

            models = re.split(r"[\s,;]+", value.strip())

        elif isinstance(value, (list, tuple)):
            models = [str(item) for item in value]

        else:
            raise ValueError("Model chain must be a comma-separated string or list")

        normalized_models: list[str] = []

        for model in models:
            model = model.strip()

            if not model:
                continue

            if model not in normalized_models:
                normalized_models.append(model)

        return normalized_models

    @field_validator(
        "RATE_LIMIT_BACKEND",
        "READING_SESSION_BACKEND",
        "READING_AUDIO_QUEUE_BACKEND",
    )
    @classmethod
    def _validate_backend(cls, value: str, info: Any) -> str:
        value = value.strip().lower()

        if value not in {"memory", "redis"}:
            raise ValueError(f"{info.field_name} must be 'memory' or 'redis'")

        return value

    @field_validator("LOG_FORMAT")
    @classmethod
    def _validate_log_format(cls, value: str) -> str:
        value = value.strip().lower()

        if value not in {"text", "json"}:
            raise ValueError("LOG_FORMAT must be 'text' or 'json'")

        return value

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        value = value.strip().upper()

        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(
                "LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
            )

        return value

    @field_validator("BOT_RUNTIME_MODE")
    @classmethod
    def _validate_bot_runtime_mode(cls, value: str) -> str:
        value = value.strip().lower()

        if value not in {"polling", "webhook"}:
            raise ValueError("BOT_RUNTIME_MODE must be 'polling' or 'webhook'")

        return value

    @field_validator("TELEGRAM_WEBHOOK_PATH")
    @classmethod
    def _validate_webhook_path(cls, value: str) -> str:
        value = value.strip() or "/webhook/telegram"

        if not value.startswith("/"):
            raise ValueError("TELEGRAM_WEBHOOK_PATH must start with '/'")

        return value

    @field_validator("TTS_PROVIDER")
    @classmethod
    def _validate_tts_provider(cls, value: str) -> str:
        value = value.strip().lower()

        if value not in {"edge", "gemini"}:
            raise ValueError(
                "TTS_PROVIDER must be 'edge' or 'gemini'"
            )

        return value

    @field_validator("TTS_PROVIDER_CHAIN", mode="before")
    @classmethod
    def _parse_tts_provider_chain(cls, value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            if not value.strip():
                return []

            providers = re.split(r"[\s,;]+", value.strip())

        elif isinstance(value, (list, tuple)):
            providers = [str(item) for item in value]

        else:
            raise ValueError(
                "TTS_PROVIDER_CHAIN must be a comma-separated string or list"
            )

        normalized_providers: list[str] = []

        for provider in providers:
            provider = provider.strip().lower()

            if not provider:
                continue

            if provider not in {"edge", "gemini"}:
                raise ValueError(
                    "TTS_PROVIDER_CHAIN must contain only edge or gemini"
                )

            if provider not in normalized_providers:
                normalized_providers.append(provider)

        return normalized_providers

    @field_validator(
        "GEMINI_RETRY_BASE_DELAY_SECONDS",
        "GEMINI_RETRY_MAX_DELAY_SECONDS",
    )
    @classmethod
    def _validate_positive_float(cls, value: float, info: Any) -> float:
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")

        return value


def _load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as error:
        raise RuntimeError(
            "Invalid application configuration. "
            "Check your .env file and environment variables.\n"
            f"{error}"
        ) from error


settings = _load_settings()

BOT_TOKEN = settings.BOT_TOKEN
GEMINI_API_KEY = settings.GEMINI_API_KEY

DEFAULT_VOICE = settings.DEFAULT_VOICE
DEFAULT_RATE = settings.DEFAULT_RATE

AI_PROVIDER_CHAIN = settings.AI_PROVIDER_CHAIN
GEMINI_TEXT_MODEL = settings.GEMINI_TEXT_MODEL
GEMINI_TEXT_MODEL_CHAIN = settings.GEMINI_TEXT_MODEL_CHAIN
GEMINI_REQUEST_TIMEOUT_SECONDS = settings.GEMINI_REQUEST_TIMEOUT_SECONDS
GEMINI_RETRY_ATTEMPTS = settings.GEMINI_RETRY_ATTEMPTS
GEMINI_RETRY_BASE_DELAY_SECONDS = settings.GEMINI_RETRY_BASE_DELAY_SECONDS
GEMINI_RETRY_MAX_DELAY_SECONDS = settings.GEMINI_RETRY_MAX_DELAY_SECONDS
GEMINI_ESTIMATED_INPUT_COST_PER_1K_CHARS_USD = (
    settings.GEMINI_ESTIMATED_INPUT_COST_PER_1K_CHARS_USD
)
GEMINI_ESTIMATED_OUTPUT_COST_PER_1K_CHARS_USD = (
    settings.GEMINI_ESTIMATED_OUTPUT_COST_PER_1K_CHARS_USD
)

GEMINI_OCR_MODEL = settings.GEMINI_OCR_MODEL
GEMINI_OCR_MODEL_CHAIN = settings.GEMINI_OCR_MODEL_CHAIN
OCR_MIN_TEXT_LENGTH = settings.OCR_MIN_TEXT_LENGTH

TTS_PROVIDER = settings.TTS_PROVIDER
TTS_PROVIDER_CHAIN = settings.TTS_PROVIDER_CHAIN
TTS_ESTIMATED_COST_PER_1K_CHARS_USD = settings.TTS_ESTIMATED_COST_PER_1K_CHARS_USD
EDGE_TTS_REQUEST_TIMEOUT_SECONDS = settings.EDGE_TTS_REQUEST_TIMEOUT_SECONDS
GEMINI_TTS_MODEL = settings.GEMINI_TTS_MODEL
GEMINI_TTS_MODEL_CHAIN = settings.GEMINI_TTS_MODEL_CHAIN
GEMINI_TTS_VOICE = settings.GEMINI_TTS_VOICE
GEMINI_TTS_FEMALE_VOICE = settings.GEMINI_TTS_FEMALE_VOICE
GEMINI_TTS_MALE_VOICE = settings.GEMINI_TTS_MALE_VOICE
GEMINI_TTS_STYLE_PROMPT = settings.GEMINI_TTS_STYLE_PROMPT
GEMINI_TTS_REQUEST_TIMEOUT_SECONDS = settings.GEMINI_TTS_REQUEST_TIMEOUT_SECONDS
GEMINI_TTS_CHUNK_MAX_LENGTH = settings.GEMINI_TTS_CHUNK_MAX_LENGTH
ADMIN_IDS = settings.ADMIN_IDS
HIDE_USER_COMMANDS = settings.HIDE_USER_COMMANDS
CLEAR_KNOWN_USER_COMMANDS_ON_STARTUP = (
    settings.CLEAR_KNOWN_USER_COMMANDS_ON_STARTUP
)

DB_PATH = settings.DB_PATH
REDIS_URL = settings.REDIS_URL
DOCUMENT_HISTORY_RETENTION_DAYS = settings.DOCUMENT_HISTORY_RETENTION_DAYS
SERVICE_METRICS_RETENTION_DAYS = settings.SERVICE_METRICS_RETENTION_DAYS
MAINTENANCE_CLEANUP_INTERVAL_SECONDS = settings.MAINTENANCE_CLEANUP_INTERVAL_SECONDS

RATE_LIMIT_MAX_EVENTS = settings.RATE_LIMIT_MAX_EVENTS
RATE_LIMIT_PERIOD_SECONDS = settings.RATE_LIMIT_PERIOD_SECONDS
RATE_LIMIT_WARNING_COOLDOWN_SECONDS = (
    settings.RATE_LIMIT_WARNING_COOLDOWN_SECONDS
)
RATE_LIMIT_BACKEND = settings.RATE_LIMIT_BACKEND

READING_SESSION_TTL_SECONDS = settings.READING_SESSION_TTL_SECONDS
READING_SESSION_BACKEND = settings.READING_SESSION_BACKEND
READING_AUDIO_QUEUE_BACKEND = settings.READING_AUDIO_QUEUE_BACKEND
READING_AUDIO_QUEUE_REDIS_KEY = settings.READING_AUDIO_QUEUE_REDIS_KEY
READING_AUDIO_QUEUE_MAX_SIZE = settings.READING_AUDIO_QUEUE_MAX_SIZE
EXPORT_AUDIO_MAX_SIZE_MB = settings.EXPORT_AUDIO_MAX_SIZE_MB
EXPORT_AUDIO_SMOOTH_MERGE_ENABLED = settings.EXPORT_AUDIO_SMOOTH_MERGE_ENABLED
EXPORT_AUDIO_CROSSFADE_MS = settings.EXPORT_AUDIO_CROSSFADE_MS

AUDIO_CACHE_ENABLED = settings.AUDIO_CACHE_ENABLED
AUDIO_CACHE_DIR = settings.AUDIO_CACHE_DIR
AUDIO_CACHE_MAX_SIZE_MB = settings.AUDIO_CACHE_MAX_SIZE_MB
AUDIO_CACHE_MAX_AGE_DAYS = settings.AUDIO_CACHE_MAX_AGE_DAYS
AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS = (
    settings.AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS
)

FREE_DAILY_TEXT_MESSAGE_LIMIT = settings.FREE_DAILY_TEXT_MESSAGE_LIMIT
FREE_DAILY_FILE_LIMIT = settings.FREE_DAILY_FILE_LIMIT
FREE_DAILY_OCR_LIMIT = settings.FREE_DAILY_OCR_LIMIT
FREE_DAILY_LINK_LIMIT = settings.FREE_DAILY_LINK_LIMIT
FREE_DAILY_SUMMARY_LIMIT = settings.FREE_DAILY_SUMMARY_LIMIT

LOG_LEVEL = settings.LOG_LEVEL
LOG_FORMAT = settings.LOG_FORMAT
LOG_SERVICE_NAME = settings.LOG_SERVICE_NAME

APP_VERSION = settings.APP_VERSION
BOT_RUNTIME_MODE = settings.BOT_RUNTIME_MODE
API_ENABLED = settings.API_ENABLED
API_HOST = settings.API_HOST
API_PORT = settings.API_PORT
API_AUTH_TOKEN = settings.API_AUTH_TOKEN
TELEGRAM_WEBHOOK_URL = settings.TELEGRAM_WEBHOOK_URL
TELEGRAM_WEBHOOK_PATH = settings.TELEGRAM_WEBHOOK_PATH
TELEGRAM_WEBHOOK_SECRET_TOKEN = settings.TELEGRAM_WEBHOOK_SECRET_TOKEN

METRICS_REDIS_STREAM_ENABLED = settings.METRICS_REDIS_STREAM_ENABLED
METRICS_REDIS_STREAM_KEY = settings.METRICS_REDIS_STREAM_KEY
METRICS_REDIS_STREAM_MAXLEN = settings.METRICS_REDIS_STREAM_MAXLEN
METRICS_ALERT_WEBHOOK_URL = settings.METRICS_ALERT_WEBHOOK_URL
METRICS_ALERT_ON_FAILURE = settings.METRICS_ALERT_ON_FAILURE
METRICS_ALERT_TIMEOUT_SECONDS = settings.METRICS_ALERT_TIMEOUT_SECONDS
