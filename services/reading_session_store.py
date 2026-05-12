# Файл: services/reading_session_store.py

import asyncio
import logging
import os
import time
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)

# Сесія читання живе 45 хвилин після останньої активності.
SESSION_TTL_SECONDS = 45 * 60

_reading_sessions: dict[int, dict[str, Any]] = {}
_user_locks: dict[int, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


def _now() -> float:
    return time.monotonic()


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


async def get_user_session_lock(user_id: int) -> asyncio.Lock:
    """
    Повертає персональний lock користувача.

    Він потрібен, щоб подвійне натискання inline-кнопок не запускало
    дві генерації аудіо одночасно.
    """
    async with _locks_guard:
        lock = _user_locks.get(user_id)

        if lock is None:
            lock = asyncio.Lock()
            _user_locks[user_id] = lock

        return lock


async def _cleanup_prefetch_task(task: asyncio.Task | None) -> None:
    """
    Безпечно очищає prefetch_task.

    Якщо задача ще виконується — скасовує її.
    Якщо задача вже завершилась і повернула список audio-файлів — видаляє їх,
    щоб тимчасові файли не залишались на диску.
    """
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


async def set_reading_session(user_id: int, session: dict[str, Any]) -> None:
    """
    Створює або замінює reading session користувача.
    Стару сесію перед цим очищає разом із prefetch-аудіо.
    """
    await cleanup_reading_session(user_id)

    lock = await get_user_session_lock(user_id)

    async with lock:
        session.setdefault("created_at", _now())
        session.setdefault("updated_at", _now())
        session.setdefault("is_generating", False)
        session.setdefault("prefetch_task", None)

        _reading_sessions[user_id] = session

    logger.info(
        "ReadingSessionStore: створено сесію user_id=%s, session_id=%s, chunks=%s",
        user_id,
        session.get("session_id"),
        len(session.get("chunks") or []),
    )


async def get_reading_session(user_id: int) -> dict[str, Any] | None:
    """
    Повертає активну reading session.

    Якщо сесія застаріла — очищає її і повертає None.
    """
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
    """
    Сумісність зі старими handlers.

    messages.py та catalog.py у твоїй актуальній структурі ще викликають
    set_reading_session_generating(...), тому функцію залишаємо.
    """
    lock = await get_user_session_lock(user_id)

    async with lock:
        session = _reading_sessions.get(user_id)

        if not session:
            return

        session["is_generating"] = is_generating
        _touch_session(session)


async def try_start_generation(user_id: int) -> bool:
    """
    Атомарно перевіряє і запускає генерацію.

    Повертає True, якщо генерацію можна почати.
    Повертає False, якщо генерація вже триває або сесії немає.
    """
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
    """
    Завершує генерацію для користувача.
    """
    await set_reading_session_generating(user_id, False)


async def update_reading_session(user_id: int, **fields: Any) -> None:
    """
    Частково оновлює поточну reading session.
    """
    lock = await get_user_session_lock(user_id)

    async with lock:
        session = _reading_sessions.get(user_id)

        if not session:
            return

        session.update(fields)
        _touch_session(session)


async def cleanup_reading_session(user_id: int) -> None:
    """
    Повністю очищає reading session користувача.
    """
    lock = await get_user_session_lock(user_id)

    async with lock:
        session = _reading_sessions.pop(user_id, None)

    if not session:
        return

    await _cleanup_prefetch_task(session.get("prefetch_task"))

    logger.info(
        "ReadingSessionStore: очищено сесію user_id=%s, session_id=%s",
        user_id,
        session.get("session_id"),
    )


async def cleanup_expired_reading_sessions() -> int:
    """
    Очищає всі застарілі sessions.

    Повертає кількість очищених сесій.
    """
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
    """
    Очищає всі reading sessions.
    Корисно при graceful shutdown бота.
    """
    for user_id in list(_reading_sessions.keys()):
        await cleanup_reading_session(user_id)

    async with _locks_guard:
        _user_locks.clear()

    logger.info("ReadingSessionStore: очищено всі сесії")
