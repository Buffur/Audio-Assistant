# Файл: config.py

from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    ADMIN_IDS: list[int] = Field(default_factory=list)

    DB_PATH: str = "bot_database.sqlite"
    REDIS_URL: str = "redis://localhost:6379/0"

    RATE_LIMIT_MAX_EVENTS: int = 8
    RATE_LIMIT_PERIOD_SECONDS: int = 10
    RATE_LIMIT_WARNING_COOLDOWN_SECONDS: int = 10

    READING_SESSION_TTL_SECONDS: int = 3600

    AUDIO_CACHE_ENABLED: bool = True
    AUDIO_CACHE_DIR: str = str(BASE_DIR / "data" / "audio_cache")

    FREE_DAILY_TEXT_MESSAGE_LIMIT: int = 100
    FREE_DAILY_FILE_LIMIT: int = 10
    FREE_DAILY_OCR_LIMIT: int = 10
    FREE_DAILY_LINK_LIMIT: int = 20
    FREE_DAILY_SUMMARY_LIMIT: int = 5

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

            for item in value.split(","):
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
        "FREE_DAILY_TEXT_MESSAGE_LIMIT",
        "FREE_DAILY_FILE_LIMIT",
        "FREE_DAILY_OCR_LIMIT",
        "FREE_DAILY_LINK_LIMIT",
        "FREE_DAILY_SUMMARY_LIMIT",
    )
    @classmethod
    def _validate_positive_int(cls, value: int, info: Any) -> int:
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

ADMIN_IDS = settings.ADMIN_IDS

DB_PATH = settings.DB_PATH
REDIS_URL = settings.REDIS_URL

RATE_LIMIT_MAX_EVENTS = settings.RATE_LIMIT_MAX_EVENTS
RATE_LIMIT_PERIOD_SECONDS = settings.RATE_LIMIT_PERIOD_SECONDS
RATE_LIMIT_WARNING_COOLDOWN_SECONDS = (
    settings.RATE_LIMIT_WARNING_COOLDOWN_SECONDS
)

READING_SESSION_TTL_SECONDS = settings.READING_SESSION_TTL_SECONDS

AUDIO_CACHE_ENABLED = settings.AUDIO_CACHE_ENABLED
AUDIO_CACHE_DIR = settings.AUDIO_CACHE_DIR

FREE_DAILY_TEXT_MESSAGE_LIMIT = settings.FREE_DAILY_TEXT_MESSAGE_LIMIT
FREE_DAILY_FILE_LIMIT = settings.FREE_DAILY_FILE_LIMIT
FREE_DAILY_OCR_LIMIT = settings.FREE_DAILY_OCR_LIMIT
FREE_DAILY_LINK_LIMIT = settings.FREE_DAILY_LINK_LIMIT
FREE_DAILY_SUMMARY_LIMIT = settings.FREE_DAILY_SUMMARY_LIMIT