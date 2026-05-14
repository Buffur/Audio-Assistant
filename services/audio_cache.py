# Файл: services/audio_cache.py

import hashlib
import logging
import shutil
import tempfile
import time
from pathlib import Path

from config import (
    AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS,
    AUDIO_CACHE_DIR,
    AUDIO_CACHE_ENABLED,
    AUDIO_CACHE_MAX_AGE_DAYS,
    AUDIO_CACHE_MAX_SIZE_MB,
)

logger = logging.getLogger(__name__)

CACHE_VERSION = "v1"
SECONDS_IN_DAY = 24 * 60 * 60

_last_cleanup_time = 0.0


def _get_cache_dir() -> Path:
    cache_dir = Path(AUDIO_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)

    return cache_dir


def build_audio_cache_key(text: str, voice: str, rate: str) -> str:
    raw_value = f"{CACHE_VERSION}|{voice}|{rate}|{text}".encode("utf-8")

    return hashlib.sha256(raw_value).hexdigest()


def get_cached_audio_path(cache_key: str) -> Path:
    return _get_cache_dir() / f"{cache_key}.ogg"


def is_audio_cache_enabled() -> bool:
    return AUDIO_CACHE_ENABLED


def get_audio_from_cache(
    text: str,
    voice: str,
    rate: str,
) -> str | None:
    if not is_audio_cache_enabled():
        return None

    cache_key = build_audio_cache_key(text, voice, rate)
    cached_path = get_cached_audio_path(cache_key)

    if not cached_path.exists():
        return None

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
    temp_file.close()

    shutil.copyfile(cached_path, temp_file.name)
    cached_path.touch()

    logger.info("AudioCache: cache hit key=%s", cache_key)

    return temp_file.name


def save_audio_to_cache(
    text: str,
    voice: str,
    rate: str,
    audio_path: str,
) -> None:
    if not is_audio_cache_enabled():
        return

    source_path = Path(audio_path)

    if not source_path.exists():
        logger.warning(
            "AudioCache: cannot save missing source file: %s",
            audio_path,
        )
        return

    cache_key = build_audio_cache_key(text, voice, rate)
    cached_path = get_cached_audio_path(cache_key)

    if cached_path.exists():
        return

    try:
        shutil.copyfile(source_path, cached_path)
        logger.info("AudioCache: audio saved key=%s", cache_key)
        maybe_cleanup_audio_cache()

    except Exception:
        logger.exception("AudioCache: failed to save file to cache: %s", audio_path)


def _remove_cache_file(file_path: Path) -> int:
    try:
        file_size = file_path.stat().st_size
        file_path.unlink()
        return file_size
    except FileNotFoundError:
        return 0
    except Exception:
        logger.exception("AudioCache: failed to remove cache file: %s", file_path)
        return 0


def _collect_cache_files(cache_dir: Path) -> list[tuple[Path, int, float]]:
    files: list[tuple[Path, int, float]] = []

    if not cache_dir.exists():
        return files

    for file_path in cache_dir.glob("*.ogg"):
        try:
            stat = file_path.stat()
        except FileNotFoundError:
            continue
        except Exception:
            logger.exception("AudioCache: failed to read cache file: %s", file_path)
            continue

        files.append((file_path, int(stat.st_size), float(stat.st_mtime)))

    return files


def cleanup_audio_cache(now: float | None = None) -> dict[str, int]:
    result = {
        "removed_files": 0,
        "removed_bytes": 0,
        "remaining_bytes": 0,
    }

    if not is_audio_cache_enabled():
        return result

    current_time = time.time() if now is None else now
    cache_dir = _get_cache_dir()
    max_age_seconds = AUDIO_CACHE_MAX_AGE_DAYS * SECONDS_IN_DAY
    max_size_bytes = AUDIO_CACHE_MAX_SIZE_MB * 1024 * 1024

    files = _collect_cache_files(cache_dir)
    remaining_files: list[tuple[Path, int, float]] = []

    for file_path, file_size, modified_at in files:
        if current_time - modified_at > max_age_seconds:
            removed_bytes = _remove_cache_file(file_path)

            if removed_bytes:
                result["removed_files"] += 1
                result["removed_bytes"] += removed_bytes

            continue

        remaining_files.append((file_path, file_size, modified_at))

    total_size = sum(file_size for _, file_size, _ in remaining_files)

    if total_size > max_size_bytes:
        for file_path, file_size, _modified_at in sorted(
            remaining_files,
            key=lambda item: item[2],
        ):
            if total_size <= max_size_bytes:
                break

            removed_bytes = _remove_cache_file(file_path)
            if not removed_bytes:
                continue

            result["removed_files"] += 1
            result["removed_bytes"] += removed_bytes
            total_size -= file_size

    result["remaining_bytes"] = max(total_size, 0)

    if result["removed_files"]:
        logger.info(
            "AudioCache: cleanup removed_files=%s removed_bytes=%s remaining_bytes=%s",
            result["removed_files"],
            result["removed_bytes"],
            result["remaining_bytes"],
        )

    return result


def maybe_cleanup_audio_cache(now: float | None = None) -> dict[str, int] | None:
    global _last_cleanup_time

    current_time = time.time() if now is None else now

    if current_time - _last_cleanup_time < AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS:
        return None

    _last_cleanup_time = current_time
    return cleanup_audio_cache(now=current_time)
