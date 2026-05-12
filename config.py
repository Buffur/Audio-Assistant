# Файл: config.py

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE_PATH = BASE_DIR / ".env"


def _load_env_file(file_path: Path = ENV_FILE_PATH) -> None:
    if not file_path.exists():
        return

    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if not key:
            continue

        os.environ.setdefault(key, value)


def _get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in .env or in system environment variables."
        )

    return value


def _parse_admin_ids(raw_admin_ids: str) -> list[int]:
    if not raw_admin_ids.strip():
        return []

    admin_ids = []

    for item in raw_admin_ids.split(","):
        item = item.strip()

        if not item:
            continue

        if not item.isdigit():
            raise RuntimeError(
                f"Invalid ADMIN_IDS value: '{item}'. "
                "ADMIN_IDS must contain only numeric Telegram user IDs separated by commas."
            )

        admin_ids.append(int(item))

    return admin_ids


def _get_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError:
        raise RuntimeError(
            f"Invalid integer value for {name}: {raw_value}"
        )


_load_env_file()

BOT_TOKEN = _get_required_env("BOT_TOKEN")
GEMINI_API_KEY = _get_required_env("GEMINI_API_KEY")

DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "uk-UA-PolinaNeural")
DEFAULT_RATE = os.getenv("DEFAULT_RATE", "+0%")

ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

if not ADMIN_IDS:
    raise RuntimeError(
        "ADMIN_IDS is empty. Add at least one Telegram user ID to .env."
    )

DB_PATH = os.getenv("DB_PATH", "bot_database.sqlite")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

RATE_LIMIT_MAX_EVENTS = _get_int_env("RATE_LIMIT_MAX_EVENTS", 8)
RATE_LIMIT_PERIOD_SECONDS = _get_int_env("RATE_LIMIT_PERIOD_SECONDS", 10)
RATE_LIMIT_WARNING_COOLDOWN_SECONDS = _get_int_env(
    "RATE_LIMIT_WARNING_COOLDOWN_SECONDS",
    10
)

READING_SESSION_TTL_SECONDS = _get_int_env(
    "READING_SESSION_TTL_SECONDS",
    3600
)

AUDIO_CACHE_ENABLED = os.getenv("AUDIO_CACHE_ENABLED", "1") == "1"
AUDIO_CACHE_DIR = os.getenv(
    "AUDIO_CACHE_DIR",
    str(BASE_DIR / "data" / "audio_cache")
)

FREE_DAILY_TEXT_MESSAGE_LIMIT = _get_int_env("FREE_DAILY_TEXT_MESSAGE_LIMIT", 100)
FREE_DAILY_FILE_LIMIT = _get_int_env("FREE_DAILY_FILE_LIMIT", 10)
FREE_DAILY_OCR_LIMIT = _get_int_env("FREE_DAILY_OCR_LIMIT", 10)
FREE_DAILY_LINK_LIMIT = _get_int_env("FREE_DAILY_LINK_LIMIT", 20)
FREE_DAILY_SUMMARY_LIMIT = _get_int_env("FREE_DAILY_SUMMARY_LIMIT", 5)