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
SESSION_KEY_PREFIX = "reading:session:"
SESSION_USERS_KEY = "reading:sessions:users"

_reading_sessions: dict[int, dict[str, Any]] = {}
_user_locks: dict[int, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


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
        session.setdefault("created_at", _now())
        session.setdefault("updated_at", _now())
        session.setdefault("is_generating", False)
        session.setdefault("prefetch_task", None)

        _reading_sessions[user_id] = session


async def set_reading_session(user_id: int, session: dict[str, Any]) -> None:
    """
    Створює або замінює reading session користувача.
    Redis backend зберігає тільки JSON-safe стан; живі asyncio tasks не
    серіалізуються і залишаються тільки для memory backend.
    """
    await cleanup_reading_session(user_id)

    session.setdefault("created_at", _now())
    session.setdefault("updated_at", _now())
    session.setdefault("is_generating", False)
    session.setdefault("prefetch_task", None)

    if _use_redis_backend():
        try:
            await _redis_store_session(user_id, session)
        except RedisError:
            logger.exception(
                "ReadingSessionStore: Redis set failed; falling back to memory "
                "user_id=%s",
                user_id,
            )
            await _memory_set_session(user_id, session)
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
        except RedisError:
            logger.exception(
                "ReadingSessionStore: Redis get failed; falling back to memory "
                "user_id=%s",
                user_id,
            )
        else:
            if session is None:
                return _reading_sessions.get(user_id)

            _touch_session(session)
            await _redis_store_session(user_id, session)
            _reading_sessions[user_id] = session
            return session

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
                    return 2
                end

                session["is_generating"] = true
                session["updated_at"] = tonumber(ARGV[2])
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
            )

            if int(result) == 1:
                return True

            if int(result) == 2:
                return False

        except RedisError:
            logger.exception(
                "ReadingSessionStore: Redis try_start failed; falling back to "
                "memory user_id=%s",
                user_id,
            )

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
            return False
        else:
            session["is_generating"] = True
            _touch_session(session)
            return True

    await _cleanup_prefetch_task(task_to_cleanup)
    return False


async def finish_generation(user_id: int) -> None:
    await set_reading_session_generating(user_id, False)


async def update_reading_session(user_id: int, **fields: Any) -> None:
    if _use_redis_backend():
        safe_fields = _sanitize_session_for_redis(fields)
        safe_fields["updated_at"] = _now()

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
        except RedisError:
            logger.exception(
                "ReadingSessionStore: Redis update failed; falling back to memory "
                "user_id=%s",
                user_id,
            )

    lock = await get_user_session_lock(user_id)

    async with lock:
        session = _reading_sessions.get(user_id)

        if not session:
            return

        session.update(fields)
        _touch_session(session)


async def cleanup_reading_session(user_id: int) -> None:
    session: dict[str, Any] | None = None

    if _use_redis_backend():
        try:
            session = await _redis_get_session(user_id)
            client = await get_redis_client()
            await client.delete(_session_key(user_id))
            await client.srem(SESSION_USERS_KEY, str(user_id))
        except RedisError:
            logger.exception(
                "ReadingSessionStore: Redis cleanup failed; falling back to "
                "memory user_id=%s",
                user_id,
            )

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
        except (RedisError, ValueError):
            logger.exception(
                "ReadingSessionStore: Redis expired cleanup failed; falling back "
                "to memory"
            )

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
