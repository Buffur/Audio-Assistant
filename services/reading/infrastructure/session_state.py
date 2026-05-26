import asyncio
import json
import logging
import os
import time
from contextlib import suppress
from typing import Any

from config import READING_SESSION_TTL_SECONDS
from services.reading.domain.models import (
    InvalidReadingSessionError,
    ReadingSession,
)

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = READING_SESSION_TTL_SECONDS
GENERATION_STALE_SECONDS = min(
    max(READING_SESSION_TTL_SECONDS // 2, 10 * 60),
    30 * 60,
)
SESSION_KEY_PREFIX = "reading:session:"
SESSION_USERS_KEY = "reading:sessions:users"

_reading_sessions: dict[int, dict[str, Any]] = {}
_user_locks: dict[int, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


class ReadingSessionStoreUnavailableError(RuntimeError):
    pass


def now() -> float:
    return time.time()


def session_key(user_id: int) -> str:
    return f"{SESSION_KEY_PREFIX}{user_id}"


def touch_session(session: dict[str, Any]) -> None:
    session["updated_at"] = now()


def is_expired(session: dict[str, Any]) -> bool:
    updated_at = session.get("updated_at") or session.get("created_at") or now()
    return (now() - float(updated_at)) > SESSION_TTL_SECONDS


def as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_generation_stale(
    session: dict[str, Any],
    current_time: float | None = None,
) -> bool:
    if not session.get("is_generating"):
        return False

    checked_at = now() if current_time is None else current_time
    started_at = as_float(
        session.get("generation_started_at")
        or session.get("updated_at")
        or session.get("created_at"),
        checked_at,
    )

    return checked_at - started_at > GENERATION_STALE_SECONDS


def recover_stale_generation(
    session: dict[str, Any],
    user_id: int,
    current_time: float | None = None,
) -> None:
    recovered_at = now() if current_time is None else current_time
    logger.warning(
        "ReadingSessionStore: recovering stale generation user_id=%s session_id=%s",
        user_id,
        session.get("session_id"),
    )
    session["is_generating"] = False
    session["generation_recovered_at"] = recovered_at


def normalized_session_mapping(session: dict[str, Any]) -> dict[str, Any]:
    return ReadingSession.from_mapping(session, now=now()).to_mapping()


def prepare_session_defaults(session: dict[str, Any]) -> None:
    normalized_session = normalized_session_mapping(session)
    session.clear()
    session.update(normalized_session)


def updates_with_generation_metadata(fields: dict[str, Any]) -> dict[str, Any]:
    updates = dict(fields)
    current_time = now()
    updates["updated_at"] = current_time

    if updates.get("is_generating") is True:
        updates["generation_started_at"] = current_time
    elif "is_generating" in updates and not updates.get("is_generating"):
        updates["generation_finished_at"] = current_time

    return updates


def raise_redis_unavailable(operation: str, user_id: int, error: Exception) -> None:
    logger.exception(
        "ReadingSessionStore: Redis %s failed; refusing memory fallback user_id=%s",
        operation,
        user_id,
    )
    raise ReadingSessionStoreUnavailableError(
        f"Redis reading session store is unavailable during {operation}."
    ) from error


def safe_remove_file(file_path: str | None) -> None:
    if not file_path:
        return

    with suppress(Exception):
        if os.path.exists(file_path):
            os.remove(file_path)


def json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, list | tuple):
        return [json_safe_value(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): json_safe_value(item)
            for key, item in value.items()
        }

    return str(value)


def sanitize_session_for_redis(session: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): json_safe_value(value)
        for key, value in session.items()
        if key != "prefetch_task"
    }


def serialize_session(session: dict[str, Any]) -> str:
    return json.dumps(
        sanitize_session_for_redis(session),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def deserialize_session(raw: str | bytes | None) -> dict[str, Any] | None:
    if raw is None:
        return None

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("ReadingSessionStore: invalid session JSON in Redis")
        return None

    if not isinstance(value, dict):
        logger.warning("ReadingSessionStore: Redis session payload is not an object")
        return None

    try:
        return normalized_session_mapping(value)
    except InvalidReadingSessionError:
        logger.exception("ReadingSessionStore: invalid Redis session payload")
        return None


async def get_user_session_lock(user_id: int) -> asyncio.Lock:
    async with _locks_guard:
        lock = _user_locks.get(user_id)

        if lock is None:
            lock = asyncio.Lock()
            _user_locks[user_id] = lock

        return lock


async def cleanup_prefetch_task(task: asyncio.Task | None) -> None:
    if task is None or not isinstance(task, asyncio.Task):
        return

    if not task.done():
        task.cancel()

        with suppress(asyncio.CancelledError):
            await task

        return

    with suppress(Exception):
        result = task.result()

        if isinstance(result, list):
            for file_path in result:
                if isinstance(file_path, str):
                    safe_remove_file(file_path)


async def cleanup_session_artifacts(session: dict[str, Any] | None) -> None:
    if not session:
        return

    await cleanup_prefetch_task(session.get("prefetch_task"))

    prefetch_audio_files = session.get("prefetch_audio_files") or []
    if isinstance(prefetch_audio_files, list):
        for file_path in prefetch_audio_files:
            if isinstance(file_path, str):
                safe_remove_file(file_path)


async def clear_user_locks() -> None:
    async with _locks_guard:
        _user_locks.clear()
