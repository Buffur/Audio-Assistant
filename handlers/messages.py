# Файл: handlers/messages.py

import asyncio
import logging
import time

from aiogram import Router, types

from handlers.callback_guards import require_private_message_user
from services.content_extractor import SUPPORTED_FORMATS_ERROR, extract_text_from_message
from services.document_history_service import (
    get_cached_summary_for_text,
    save_document_history_from_message,
)
from services.reading_service import (
    cleanup_session,
    is_audio_generation_active,
    reply_with_voice,
    safe_delete_message,
    send_audio_chunk,
    start_reading_session,
)
from services.ocr import OCR_NO_TEXT_MESSAGE
from services.usage_limits_service import (
    detect_input_usage_type,
    refund_input_processing,
    reserve_input_processing,
)
from texts.limits import get_limit_reached_text
from texts.messages import (
    ANALYZING_MATERIAL_TEXT,
    GENERIC_TEXT_EXTRACT_ERROR,
    PREPARING_FIRST_AUDIO_TEXT,
    SPLITTING_TEXT_STATUS,
    TEXT_SPLIT_ERROR,
    UNKNOWN_COMMAND_TEXT,
    UNSUPPORTED_MESSAGE_TEXT,
    UNSUPPORTED_MESSAGE_REPEAT_TEXT,
    WAIT_CURRENT_AUDIO_REQUEST_TEXT,
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

TEXT_ONLY_EXTRACTION_ERRORS = {
    SUPPORTED_FORMATS_ERROR,
    OCR_NO_TEXT_MESSAGE,
}


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
            "Messages: repeated unsupported message user_id=%s message_id=%s",
            user_id,
            getattr(message, "message_id", None),
        )
        await message.answer(UNSUPPORTED_MESSAGE_REPEAT_TEXT)
        return

    await message.answer(UNSUPPORTED_MESSAGE_TEXT)


async def _safe_edit_status(status_msg: types.Message, text: str) -> None:
    try:
        await status_msg.edit_text(text)
    except Exception:
        logger.exception(
            "Messages: failed to update processing status user_id=%s",
            getattr(getattr(status_msg, "chat", None), "id", None),
        )


async def _refund_reserved_input(user_id: int, usage_type: str) -> None:
    try:
        await refund_input_processing(user_id, usage_type)
    except Exception:
        logger.exception(
            "Messages: failed to refund reserved usage user_id=%s usage_type=%s",
            user_id,
            usage_type,
        )


async def _process_message(message: types.Message, user_id: int) -> None:
    if not _is_supported_processing_message(message):
        await _handle_unsupported_message(message, user_id)
        return

    if message.text and message.text.startswith("/"):
        await message.answer(UNKNOWN_COMMAND_TEXT)
        return

    if await is_audio_generation_active(user_id):
        await message.answer(WAIT_CURRENT_AUDIO_REQUEST_TEXT)
        return

    await cleanup_session(user_id)

    usage_type = detect_input_usage_type(message)

    if not await reserve_input_processing(user_id, usage_type):
        await message.answer(get_limit_reached_text(usage_type))
        return

    status_msg = await message.answer(ANALYZING_MATERIAL_TEXT)

    try:
        text = await extract_text_from_message(
            message=message,
            status_msg=status_msg,
        )
    except Exception:
        await _refund_reserved_input(user_id, usage_type)
        await safe_delete_message(status_msg)
        raise

    if not text or not text.strip() or is_error_text(text):
        error_text = text if is_error_text(text) else GENERIC_TEXT_EXTRACT_ERROR
        await _refund_reserved_input(user_id, usage_type)

        if error_text in TEXT_ONLY_EXTRACTION_ERRORS:
            await safe_delete_message(status_msg)
            await message.answer(error_text)
            return

        await reply_with_voice(message, user_id, error_text, status_msg)
        return

    text, was_limited = _limit_extracted_text(text)

    if was_limited:
        await message.answer(
            build_text_was_limited_text(MAX_EXTRACTED_TEXT_LENGTH)
        )

    await _safe_edit_status(status_msg, SPLITTING_TEXT_STATUS)
    chunks = split_text(text)

    if not chunks:
        logger.warning(
            "Messages: split_text повернув порожній список для user_id=%s",
            user_id,
        )
        await _refund_reserved_input(user_id, usage_type)
        await reply_with_voice(
            message,
            user_id,
            TEXT_SPLIT_ERROR,
            status_msg,
        )
        return

    await _safe_edit_status(status_msg, PREPARING_FIRST_AUDIO_TEXT)

    document_id = await save_document_history_from_message(
        user_id=user_id,
        message=message,
        text=text,
        chunks=chunks,
    )
    cached_summary = await get_cached_summary_for_text(
        user_id=user_id,
        text=text,
        chunks=chunks,
        exclude_document_id=document_id,
    )
    cached_summary_kwargs = {}

    if cached_summary is not None:
        cached_summary_kwargs = {
            "summary_text": cached_summary.summary_text,
            "summary_voice_file_ids": cached_summary.summary_voice_file_ids,
            "summary_voice_voice": cached_summary.summary_voice_voice,
            "summary_voice_rate": cached_summary.summary_voice_rate,
            "summary_voice_provider": cached_summary.summary_voice_provider,
        }

    await start_reading_session(
        user_id=user_id,
        chunks=chunks,
        catalog_document_id=document_id,
        cleanup_existing=False,
        **cached_summary_kwargs,
    )

    if len(chunks) > 1:
        await safe_delete_message(status_msg)
        await message.answer(build_large_text_split_text(len(chunks)))
    else:
        await safe_delete_message(status_msg)

    await send_audio_chunk(message, user_id)


@router.message()
async def handle_message(message: types.Message) -> None:
    user_id = await require_private_message_user(message)

    if user_id is None:
        logger.warning(
            "Messages: ignored message outside private user boundary. "
            "message_id=%s, chat_id=%s",
            getattr(message, "message_id", None),
            getattr(getattr(message, "chat", None), "id", None),
        )
        return

    lock = _reserve_user_processing_lock(user_id)

    try:
        async with lock:
            await _process_message(message, user_id)
    finally:
        _release_user_processing_lock(user_id)
