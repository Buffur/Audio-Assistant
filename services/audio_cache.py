# Файл: services/audio_cache.py

import hashlib
import logging
import shutil
import tempfile
from pathlib import Path

from config import AUDIO_CACHE_DIR, AUDIO_CACHE_ENABLED

logger = logging.getLogger(__name__)

CACHE_VERSION = "v1"


def _get_cache_dir() -> Path:
    """
    Повертає директорію кешу аудіо і створює її, якщо потрібно.
    """
    cache_dir = Path(AUDIO_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)

    return cache_dir


def build_audio_cache_key(text: str, voice: str, rate: str) -> str:
    """
    Формує стабільний cache key для TTS.

    У ключ входить:
    - версія кешу;
    - текст;
    - голос;
    - швидкість.

    Якщо пізніше зміниться TTS provider або спосіб генерації,
    достатньо змінити CACHE_VERSION.
    """
    raw_value = f"{CACHE_VERSION}|{voice}|{rate}|{text}".encode("utf-8")

    return hashlib.sha256(raw_value).hexdigest()


def get_cached_audio_path(cache_key: str) -> Path:
    """
    Повертає шлях до cached .ogg файлу.
    """
    return _get_cache_dir() / f"{cache_key}.ogg"


def is_audio_cache_enabled() -> bool:
    """
    Перевіряє, чи увімкнено кешування аудіо.
    """
    return AUDIO_CACHE_ENABLED


def get_audio_from_cache(
    text: str,
    voice: str,
    rate: str
) -> str | None:
    """
    Якщо аудіо вже є в cache, повертає шлях до тимчасової копії.

    Важливо:
    voice_sender після надсилання видаляє файл.
    Тому ми не повертаємо сам cached-файл, а створюємо копію.
    """
    if not is_audio_cache_enabled():
        return None

    cache_key = build_audio_cache_key(text, voice, rate)
    cached_path = get_cached_audio_path(cache_key)

    if not cached_path.exists():
        return None

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
    temp_file.close()

    shutil.copyfile(cached_path, temp_file.name)

    logger.info("AudioCache: cache hit key=%s", cache_key)

    return temp_file.name


def save_audio_to_cache(
    text: str,
    voice: str,
    rate: str,
    audio_path: str
) -> None:
    """
    Зберігає згенерований .ogg файл у cache.

    Якщо кеш уже існує — не перезаписуємо його.
    """
    if not is_audio_cache_enabled():
        return

    source_path = Path(audio_path)

    if not source_path.exists():
        logger.warning(
            "AudioCache: неможливо зберегти неіснуючий файл у cache: %s",
            audio_path
        )
        return

    cache_key = build_audio_cache_key(text, voice, rate)
    cached_path = get_cached_audio_path(cache_key)

    if cached_path.exists():
        return

    try:
        shutil.copyfile(source_path, cached_path)
        logger.info("AudioCache: audio saved key=%s", cache_key)

    except Exception:
        logger.exception(
            "AudioCache: не вдалося зберегти файл у cache: %s",
            audio_path
        )