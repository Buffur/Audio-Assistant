# Файл: handlers/messages.py

import asyncio
import logging
import time
import uuid

from aiogram import Router, types

from services.content_extractor import extract_text_from_message
from services.document_history_service import save_document_history_from_message
from services.reading_service import (
    cleanup_session,
    reply_with_voice,
    safe_delete_message,
    send_audio_chunk,
)
from services.reading_session_store import (
    set_reading_session,
)
from services.usage_limits_service import (
    detect_input_usage_type,
    reserve_input_processing,
)
from texts.limits import get_limit_reached_text
from texts.messages import (
    ANALYZING_MATERIAL_TEXT,
    GENERIC_TEXT_EXTRACT_ERROR,
    TEXT_SPLIT_ERROR,
    UNKNOWN_COMMAND_TEXT,
    UNSUPPORTED_MESSAGE_TEXT,
    build_large_text_split_text,
    build_text_was_limited_text,
)
from utils.splitter import split_text
from utils.text_checks import is_error_text

router = Router()
logger = logging.getLogger(__name__)

MAX_EXTRACTED_TEXT_LENGTH = 60000
UNSUPPORTED_MESSAGE_WARNING_COOLDOWN_SECONDS = 30

_user_processing_locks: dict[int, asyncio.Lock] = {}
_user_processing_lock_usage: dict[int, int] = {}
_last_unsupported_message_warning_time: dict[int, float] = {}


def _reserve_user_processing_lock(user_id: int) -> asyncio.Lock:
    lock = _user_processing_locks.get(user_id)

    if lock is None:
        lock = asyncio.Lock()
        _user_processing_locks[user_id] = lock

    _user_processing_lock_usage[user_id] = (
        _user_processing_lock_usage.get(user_id, 0) + 1
    )

    return lock


def _release_user_processing_lock(user_id: int) -> None:
    usage_count = _user_processing_lock_usage.get(user_id, 0) - 1

    if usage_count > 0:
        _user_processing_lock_usage[user_id] = usage_count
        return

    _user_processing_lock_usage.pop(user_id, None)

    lock = _user_processing_locks.get(user_id)

    if lock is not None and not lock.locked():
        _user_processing_locks.pop(user_id, None)


def _limit_extracted_text(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_EXTRACTED_TEXT_LENGTH:
        return text, False

    return text[:MAX_EXTRACTED_TEXT_LENGTH].strip(), True


def _is_supported_processing_message(message: types.Message) -> bool:
    return bool(
        getattr(message, "text", None)
        or getattr(message, "photo", None)
        or getattr(message, "document", None)
    )


def _can_send_unsupported_message_warning(user_id: int, now: float) -> bool:
    last_warning_time = _last_unsupported_message_warning_time.get(user_id)

    if last_warning_time is None:
        _last_unsupported_message_warning_time[user_id] = now
        return True

    if now - last_warning_time >= UNSUPPORTED_MESSAGE_WARNING_COOLDOWN_SECONDS:
        _last_unsupported_message_warning_time[user_id] = now
        return True

    return False


async def _handle_unsupported_message(
    message: types.Message,
    user_id: int
) -> None:
    now = time.monotonic()

    if not _can_send_unsupported_message_warning(user_id, now):
        logger.info(
            "Messages: unsupported message silently ignored user_id=%s message_id=%s",
            user_id,
            getattr(message, "message_id", None),
        )
        return

    await message.answer(UNSUPPORTED_MESSAGE_TEXT)


def _generate_session_id() -> str:
    return uuid.uuid4().hex[:12]


async def _process_message(message: types.Message, user_id: int) -> None:
    if not _is_supported_processing_message(message):
        await _handle_unsupported_message(message, user_id)
        return

    await cleanup_session(user_id)

    if message.text and message.text.startswith("/"):
        await message.answer(UNKNOWN_COMMAND_TEXT)
        return

    usage_type = detect_input_usage_type(message)

    if not await reserve_input_processing(user_id, usage_type):
        await message.answer(get_limit_reached_text(usage_type))
        return

    status_msg = await message.answer(ANALYZING_MATERIAL_TEXT)

    text = await extract_text_from_message(
        message=message,
        status_msg=status_msg,
    )

    if not text or not text.strip() or is_error_text(text):
        error_text = text if is_error_text(text) else GENERIC_TEXT_EXTRACT_ERROR
        await reply_with_voice(message, user_id, error_text, status_msg)
        return

    text, was_limited = _limit_extracted_text(text)

    if was_limited:
        await message.answer(
            build_text_was_limited_text(MAX_EXTRACTED_TEXT_LENGTH)
        )

    chunks = split_text(text)

    if not chunks:
        logger.warning(
            "Messages: split_text повернув порожній список для user_id=%s",
            user_id,
        )
        await reply_with_voice(
            message,
            user_id,
            TEXT_SPLIT_ERROR,
            status_msg,
        )
        return

    await save_document_history_from_message(
        user_id=user_id,
        message=message,
        text=text,
        chunks=chunks,
    )

    await set_reading_session(
        user_id=user_id,
        session={
            "session_id": _generate_session_id(),
            "chunks": chunks,
            "index": 0,
            "is_generating": True,
            "prefetch_task": None,
        },
    )

    if len(chunks) > 1:
        await safe_delete_message(status_msg)
        await message.answer(build_large_text_split_text(len(chunks)))
    else:
        await safe_delete_message(status_msg)

    await send_audio_chunk(message, user_id)


@router.message()
async def handle_message(message: types.Message) -> None:
    if message.from_user is None:
        logger.warning(
            "Messages: отримано повідомлення без from_user. "
            "message_id=%s, chat_id=%s",
            message.message_id,
            getattr(message.chat, "id", None),
        )
        return

    user_id = message.from_user.id
    lock = _reserve_user_processing_lock(user_id)

    try:
        async with lock:
            await _process_message(message, user_id)
    finally:
        _release_user_processing_lock(user_id)
