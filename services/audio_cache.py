# Файл: services/audio_cache.py

import hashlib
import contextlib
import json
import logging
import os
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
OWNER_LOCK_TIMEOUT_SECONDS = 2.0
OWNER_LOCK_SLEEP_SECONDS = 0.02

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


def get_audio_cache_owner_path(cache_key: str) -> Path:
    return _get_cache_dir() / f"{cache_key}.owners.json"


def _get_cache_lock_path(cache_key: str) -> Path:
    return _get_cache_dir() / f"{cache_key}.lock"


def is_audio_cache_enabled() -> bool:
    return AUDIO_CACHE_ENABLED


def _normalize_user_id(user_id: int | None) -> int | None:
    if isinstance(user_id, int) and not isinstance(user_id, bool) and user_id > 0:
        return user_id

    return None


def _read_cache_owners(owner_path: Path) -> set[int]:
    try:
        payload = json.loads(owner_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except Exception:
        logger.exception("AudioCache: failed to read owner index: %s", owner_path)
        return set()

    raw_owners = payload.get("owners") if isinstance(payload, dict) else None

    if not isinstance(raw_owners, list):
        return set()

    return {
        owner
        for owner in raw_owners
        if isinstance(owner, int) and not isinstance(owner, bool) and owner > 0
    }


def _write_cache_owners(owner_path: Path, owners: set[int]) -> None:
    owner_path.parent.mkdir(parents=True, exist_ok=True)

    if not owners:
        with contextlib.suppress(FileNotFoundError):
            owner_path.unlink()
        return

    payload = {
        "version": 1,
        "owners": sorted(owners),
        "updated_at": int(time.time()),
    }
    temp_path = owner_path.with_suffix(f"{owner_path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temp_path.replace(owner_path)


class _CacheOwnerLock:
    def __init__(self, cache_key: str) -> None:
        self.lock_path = _get_cache_lock_path(cache_key)
        self._fd: int | None = None

    def __enter__(self) -> "_CacheOwnerLock":
        deadline = time.monotonic() + OWNER_LOCK_TIMEOUT_SECONDS

        while True:
            try:
                self._fd = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self._fd, str(os.getpid()).encode("ascii", errors="ignore"))
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Audio cache owner lock timed out: {self.lock_path}"
                    )

                time.sleep(OWNER_LOCK_SLEEP_SECONDS)

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

        with contextlib.suppress(FileNotFoundError):
            self.lock_path.unlink()


def _register_cache_owner(
    cache_key: str,
    user_id: int | None,
    *,
    create_index: bool = True,
) -> None:
    normalized_user_id = _normalize_user_id(user_id)

    if normalized_user_id is None:
        return

    owner_path = get_audio_cache_owner_path(cache_key)

    if not create_index and not owner_path.exists():
        return

    try:
        with _CacheOwnerLock(cache_key):
            owners = _read_cache_owners(owner_path)
            owners.add(normalized_user_id)
            _write_cache_owners(owner_path, owners)
    except Exception:
        logger.exception(
            "AudioCache: failed to register cache owner key=%s user_id=%s",
            cache_key,
            normalized_user_id,
        )


def _remove_cache_entry(file_path: Path) -> int:
    cache_key = file_path.stem
    removed_bytes = _remove_cache_file(file_path)
    owner_path = get_audio_cache_owner_path(cache_key)

    with contextlib.suppress(FileNotFoundError):
        owner_path.unlink()

    with contextlib.suppress(FileNotFoundError):
        _get_cache_lock_path(cache_key).unlink()

    return removed_bytes


def get_audio_from_cache(
    text: str,
    voice: str,
    rate: str,
    user_id: int | None = None,
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
    _register_cache_owner(cache_key, user_id, create_index=False)

    logger.info("AudioCache: cache hit key=%s", cache_key)

    return temp_file.name


def save_audio_to_cache(
    text: str,
    voice: str,
    rate: str,
    audio_path: str,
    user_id: int | None = None,
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
        _register_cache_owner(cache_key, user_id, create_index=False)
        return

    try:
        shutil.copyfile(source_path, cached_path)
        _register_cache_owner(cache_key, user_id, create_index=True)
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
            removed_bytes = _remove_cache_entry(file_path)

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

            removed_bytes = _remove_cache_entry(file_path)
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


def clear_audio_cache() -> dict[str, int]:
    """
    Повністю очищає shared audio cache.

    Це адміністративна операція для maintenance/debug scenarios.
    Для /delete_my_data використовуйте delete_user_audio_cache(), щоб не
    інвалідовувати кеш інших користувачів.
    """
    result = {
        "removed_files": 0,
        "removed_bytes": 0,
    }

    if not is_audio_cache_enabled():
        return result

    cache_dir = _get_cache_dir()

    for file_path in cache_dir.glob("*.ogg"):
        removed_bytes = _remove_cache_entry(file_path)

        if removed_bytes:
            result["removed_files"] += 1
            result["removed_bytes"] += removed_bytes

    if result["removed_files"]:
        logger.info(
            "AudioCache: full clear removed_files=%s removed_bytes=%s",
            result["removed_files"],
            result["removed_bytes"],
        )

    return result


def delete_user_audio_cache(user_id: int) -> dict[str, int]:
    result = {
        "removed_files": 0,
        "removed_bytes": 0,
        "owner_links_removed": 0,
    }
    normalized_user_id = _normalize_user_id(user_id)

    if not is_audio_cache_enabled() or normalized_user_id is None:
        return result

    cache_dir = _get_cache_dir()

    for owner_path in cache_dir.glob("*.owners.json"):
        cache_key = owner_path.name.removesuffix(".owners.json")
        cached_path = get_cached_audio_path(cache_key)

        try:
            with _CacheOwnerLock(cache_key):
                owners = _read_cache_owners(owner_path)

                if normalized_user_id not in owners:
                    continue

                owners.discard(normalized_user_id)
                result["owner_links_removed"] += 1

                if owners:
                    _write_cache_owners(owner_path, owners)
                    continue

                removed_bytes = _remove_cache_file(cached_path)
                with contextlib.suppress(FileNotFoundError):
                    owner_path.unlink()

                if removed_bytes:
                    result["removed_files"] += 1
                    result["removed_bytes"] += removed_bytes

        except Exception:
            logger.exception(
                "AudioCache: failed to delete user cache ownership user_id=%s key=%s",
                normalized_user_id,
                cache_key,
            )

    if result["owner_links_removed"] or result["removed_files"]:
        logger.info(
            "AudioCache: user cache cleanup user_id=%s owner_links_removed=%s "
            "removed_files=%s removed_bytes=%s",
            normalized_user_id,
            result["owner_links_removed"],
            result["removed_files"],
            result["removed_bytes"],
        )

    return result


def maybe_cleanup_audio_cache(now: float | None = None) -> dict[str, int] | None:
    global _last_cleanup_time

    current_time = time.time() if now is None else now

    if current_time - _last_cleanup_time < AUDIO_CACHE_CLEANUP_INTERVAL_SECONDS:
        return None

    _last_cleanup_time = current_time
    return cleanup_audio_cache(now=current_time)
