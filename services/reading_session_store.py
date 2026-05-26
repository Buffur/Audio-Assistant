# Файл: services/reading_session_store.py

import asyncio
import json
import logging
import os
import time
from contextlib import suppress
from typing import Any

from redis.exceptions import RedisError

from config import READING_SESSION_BACKEND, READING_SESSION_TTL_SECONDS
from services.redis_client import get_redis_client

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


def _now() -> float:
    return time.time()


def _use_redis_backend() -> bool:
    return READING_SESSION_BACKEND == "redis"


def _session_key(user_id: int) -> str:
    return f"{SESSION_KEY_PREFIX}{user_id}"


def _touch_session(session: dict[str, Any]) -> None:
    session["updated_at"] = _now()


def _is_expired(session: dict[str, Any]) -> bool:
    updated_at = session.get("updated_at") or session.get("created_at") or _now()
    return (_now() - float(updated_at)) > SESSION_TTL_SECONDS


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_generation_stale(
    session: dict[str, Any],
    now: float | None = None,
) -> bool:
    if not session.get("is_generating"):
        return False

    current_time = _now() if now is None else now
    started_at = _as_float(
        session.get("generation_started_at")
        or session.get("updated_at")
        or session.get("created_at"),
        current_time,
    )

    return current_time - started_at > GENERATION_STALE_SECONDS


def _recover_stale_generation(
    session: dict[str, Any],
    user_id: int,
    now: float | None = None,
) -> None:
    current_time = _now() if now is None else now
    logger.warning(
        "ReadingSessionStore: recovering stale generation user_id=%s session_id=%s",
        user_id,
        session.get("session_id"),
    )
    session["is_generating"] = False
    session["generation_recovered_at"] = current_time


def _prepare_session_defaults(session: dict[str, Any]) -> None:
    current_time = _now()

    session.setdefault("created_at", current_time)
    session.setdefault("updated_at", current_time)
    session.setdefault("is_generating", False)
    session.setdefault("prefetch_task", None)

    if session.get("is_generating") and not session.get("generation_started_at"):
        session["generation_started_at"] = current_time


def _updates_with_generation_metadata(fields: dict[str, Any]) -> dict[str, Any]:
    updates = dict(fields)
    current_time = _now()
    updates["updated_at"] = current_time

    if updates.get("is_generating") is True:
        updates["generation_started_at"] = current_time
    elif "is_generating" in updates and not updates.get("is_generating"):
        updates["generation_finished_at"] = current_time

    return updates


def _raise_redis_unavailable(operation: str, user_id: int, error: Exception) -> None:
    logger.exception(
        "ReadingSessionStore: Redis %s failed; refusing memory fallback user_id=%s",
        operation,
        user_id,
    )
    raise ReadingSessionStoreUnavailableError(
        f"Redis reading session store is unavailable during {operation}."
    ) from error


def _safe_remove_file(file_path: str | None) -> None:
    if not file_path:
        return

    with suppress(Exception):
        if os.path.exists(file_path):
            os.remove(file_path)


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, list | tuple):
        return [_json_safe_value(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): _json_safe_value(item)
            for key, item in value.items()
        }

    return str(value)


def _sanitize_session_for_redis(session: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _json_safe_value(value)
        for key, value in session.items()
        if key != "prefetch_task"
    }


def _serialize_session(session: dict[str, Any]) -> str:
    return json.dumps(
        _sanitize_session_for_redis(session),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _deserialize_session(raw: str | bytes | None) -> dict[str, Any] | None:
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

    return value


async def get_user_session_lock(user_id: int) -> asyncio.Lock:
    """
    Повертає локальний персональний lock користувача.

    Для Redis backend критичний start-generation path додатково захищений
    Lua-скриптом, бо локальний lock не працює між різними процесами.
    """
    async with _locks_guard:
        lock = _user_locks.get(user_id)

        if lock is None:
            lock = asyncio.Lock()
            _user_locks[user_id] = lock

        return lock


async def _cleanup_prefetch_task(task: asyncio.Task | None) -> None:
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
                    _safe_remove_file(file_path)


async def _cleanup_session_artifacts(session: dict[str, Any] | None) -> None:
    if not session:
        return

    await _cleanup_prefetch_task(session.get("prefetch_task"))

    prefetch_audio_files = session.get("prefetch_audio_files") or []
    if isinstance(prefetch_audio_files, list):
        for file_path in prefetch_audio_files:
            if isinstance(file_path, str):
                _safe_remove_file(file_path)


async def _redis_get_session(user_id: int) -> dict[str, Any] | None:
    client = await get_redis_client()
    raw_session = await client.get(_session_key(user_id))
    session = _deserialize_session(raw_session)

    if session is None:
        await client.srem(SESSION_USERS_KEY, str(user_id))
        return None

    return session


async def _redis_store_session(user_id: int, session: dict[str, Any]) -> None:
    client = await get_redis_client()
    await client.setex(
        _session_key(user_id),
        SESSION_TTL_SECONDS,
        _serialize_session(session),
    )
    await client.sadd(SESSION_USERS_KEY, str(user_id))


async def _memory_set_session(user_id: int, session: dict[str, Any]) -> None:
    await cleanup_reading_session(user_id)

    lock = await get_user_session_lock(user_id)

    async with lock:
        _prepare_session_defaults(session)

        _reading_sessions[user_id] = session


async def set_reading_session(user_id: int, session: dict[str, Any]) -> None:
    """
    Створює або замінює reading session користувача.
    Redis backend зберігає тільки JSON-safe стан; живі asyncio tasks не
    серіалізуються і залишаються тільки для memory backend.
    """
    await cleanup_reading_session(user_id)

    _prepare_session_defaults(session)

    if _use_redis_backend():
        try:
            await _redis_store_session(user_id, session)
        except RedisError as error:
            _raise_redis_unavailable("set", user_id, error)
        else:
            _reading_sessions[user_id] = _sanitize_session_for_redis(session)
    else:
        await _memory_set_session(user_id, session)

    logger.info(
        "ReadingSessionStore: створено сесію user_id=%s, session_id=%s, chunks=%s",
        user_id,
        session.get("session_id"),
        len(session.get("chunks") or []),
    )


async def get_reading_session(user_id: int) -> dict[str, Any] | None:
    if _use_redis_backend():
        try:
            session = await _redis_get_session(user_id)

            if session is None:
                return None

            if _is_generation_stale(session):
                _recover_stale_generation(session, user_id)

            _touch_session(session)
            await _redis_store_session(user_id, session)
            _reading_sessions[user_id] = session
            return session
        except RedisError as error:
            _raise_redis_unavailable("get", user_id, error)

    task_to_cleanup: asyncio.Task | None = None
    lock = await get_user_session_lock(user_id)

    async with lock:
        session = _reading_sessions.get(user_id)

        if not session:
            return None

        if _is_expired(session):
            logger.info(
                "ReadingSessionStore: сесія user_id=%s застаріла, очищаю",
                user_id,
            )
            task_to_cleanup = session.get("prefetch_task")
            _reading_sessions.pop(user_id, None)
        else:
            if _is_generation_stale(session):
                _recover_stale_generation(session, user_id)

            _touch_session(session)
            return session

    await _cleanup_prefetch_task(task_to_cleanup)
    return None


async def has_reading_session(user_id: int) -> bool:
    return await get_reading_session(user_id) is not None


async def set_reading_session_generating(user_id: int, is_generating: bool) -> None:
    await update_reading_session(user_id, is_generating=is_generating)


async def try_start_generation(user_id: int) -> bool:
    """
    Атомарно перевіряє і запускає генерацію.
    """
    if _use_redis_backend():
        try:
            client = await get_redis_client()
            result = await client.eval(
                """
                local raw_session = redis.call("GET", KEYS[1])
                if not raw_session then
                    redis.call("SREM", KEYS[2], ARGV[1])
                    return 0
                end

                local session = cjson.decode(raw_session)
                if session["is_generating"] then
                    local generation_started_at = tonumber(
                        session["generation_started_at"]
                        or session["updated_at"]
                        or session["created_at"]
                        or ARGV[2]
                    )

                    if tonumber(ARGV[2]) - generation_started_at <= tonumber(ARGV[4]) then
                        return 2
                    end

                    session["is_generating"] = false
                    session["generation_recovered_at"] = tonumber(ARGV[2])
                end

                session["is_generating"] = true
                session["updated_at"] = tonumber(ARGV[2])
                session["generation_started_at"] = tonumber(ARGV[2])
                redis.call("SETEX", KEYS[1], tonumber(ARGV[3]), cjson.encode(session))
                redis.call("SADD", KEYS[2], ARGV[1])
                return 1
                """,
                2,
                _session_key(user_id),
                SESSION_USERS_KEY,
                str(user_id),
                str(_now()),
                str(SESSION_TTL_SECONDS),
                str(GENERATION_STALE_SECONDS),
            )

            if int(result) == 1:
                return True

            if int(result) == 2:
                return False

        except RedisError as error:
            _raise_redis_unavailable("try_start", user_id, error)

    task_to_cleanup: asyncio.Task | None = None
    lock = await get_user_session_lock(user_id)

    async with lock:
        session = _reading_sessions.get(user_id)

        if not session:
            return False

        if _is_expired(session):
            task_to_cleanup = session.get("prefetch_task")
            _reading_sessions.pop(user_id, None)
        elif session.get("is_generating"):
            if not _is_generation_stale(session):
                return False

            _recover_stale_generation(session, user_id)
            session["is_generating"] = True
            session["generation_started_at"] = _now()
            _touch_session(session)
            return True
        else:
            session["is_generating"] = True
            session["generation_started_at"] = _now()
            _touch_session(session)
            return True

    await _cleanup_prefetch_task(task_to_cleanup)
    return False


async def finish_generation(user_id: int) -> None:
    await set_reading_session_generating(user_id, False)


async def update_reading_session(user_id: int, **fields: Any) -> None:
    if _use_redis_backend():
        safe_fields = _sanitize_session_for_redis(
            _updates_with_generation_metadata(fields)
        )

        try:
            client = await get_redis_client()
            result = await client.eval(
                """
                local raw_session = redis.call("GET", KEYS[1])
                if not raw_session then
                    redis.call("SREM", KEYS[2], ARGV[1])
                    return 0
                end

                local session = cjson.decode(raw_session)
                local updates = cjson.decode(ARGV[2])

                for key, value in pairs(updates) do
                    session[key] = value
                end

                redis.call("SETEX", KEYS[1], tonumber(ARGV[3]), cjson.encode(session))
                redis.call("SADD", KEYS[2], ARGV[1])
                return 1
                """,
                2,
                _session_key(user_id),
                SESSION_USERS_KEY,
                str(user_id),
                json.dumps(safe_fields, ensure_ascii=False),
                str(SESSION_TTL_SECONDS),
            )

            if result:
                local_session = _reading_sessions.setdefault(user_id, {})
                local_session.update(safe_fields)
            return
        except RedisError as error:
            _raise_redis_unavailable("update", user_id, error)

    lock = await get_user_session_lock(user_id)

    async with lock:
        session = _reading_sessions.get(user_id)

        if not session:
            return

        session.update(_updates_with_generation_metadata(fields))
        _touch_session(session)


async def cleanup_reading_session(user_id: int) -> None:
    session: dict[str, Any] | None = None

    if _use_redis_backend():
        try:
            session = await _redis_get_session(user_id)
            client = await get_redis_client()
            await client.delete(_session_key(user_id))
            await client.srem(SESSION_USERS_KEY, str(user_id))
        except RedisError as error:
            _raise_redis_unavailable("cleanup", user_id, error)

    lock = await get_user_session_lock(user_id)

    async with lock:
        local_session = _reading_sessions.pop(user_id, None)

    session = session or local_session

    if not session:
        return

    await _cleanup_session_artifacts(session)

    logger.info(
        "ReadingSessionStore: очищено сесію user_id=%s, session_id=%s",
        user_id,
        session.get("session_id"),
    )


async def cleanup_expired_reading_sessions() -> int:
    if _use_redis_backend():
        try:
            client = await get_redis_client()
            user_ids = await client.smembers(SESSION_USERS_KEY)
            stale_user_ids: list[str] = []

            for raw_user_id in user_ids:
                if not await client.exists(_session_key(int(raw_user_id))):
                    stale_user_ids.append(str(raw_user_id))

            if stale_user_ids:
                await client.srem(SESSION_USERS_KEY, *stale_user_ids)

            return len(stale_user_ids)
        except RedisError as error:
            _raise_redis_unavailable("expired_cleanup", 0, error)
        except ValueError:
            logger.exception("ReadingSessionStore: invalid Redis session user id")
            return 0

    expired_user_ids: list[int] = []

    for user_id in list(_reading_sessions.keys()):
        lock = await get_user_session_lock(user_id)

        async with lock:
            session = _reading_sessions.get(user_id)

            if session and _is_expired(session):
                expired_user_ids.append(user_id)

    for user_id in expired_user_ids:
        await cleanup_reading_session(user_id)

    if expired_user_ids:
        logger.info(
            "ReadingSessionStore: очищено застарілих сесій: %s",
            len(expired_user_ids),
        )

    return len(expired_user_ids)


async def cleanup_all_reading_sessions() -> None:
    if _use_redis_backend():
        async with _locks_guard:
            _user_locks.clear()

        _reading_sessions.clear()
        logger.info(
            "ReadingSessionStore: локальний стан очищено; Redis sessions "
            "залишено до TTL"
        )
        return

    for user_id in list(_reading_sessions.keys()):
        await cleanup_reading_session(user_id)

    async with _locks_guard:
        _user_locks.clear()

    logger.info("ReadingSessionStore: очищено всі сесії")
