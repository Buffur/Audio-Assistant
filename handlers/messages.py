# Файл: handlers/messages.py

import logging
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
    has_reading_session,
    set_reading_session,
    set_reading_session_generating,
)
from services.usage_limits_service import (
    can_process_input,
    detect_input_usage_type,
    record_input_processed,
)
from texts.limits import get_limit_reached_text
from texts.messages import (
    ANALYZING_MATERIAL_TEXT,
    GENERIC_TEXT_EXTRACT_ERROR,
    TEXT_SPLIT_ERROR,
    UNKNOWN_COMMAND_TEXT,
    build_large_text_split_text,
    build_text_was_limited_text,
)
from utils.splitter import split_text
from utils.text_checks import is_error_text

router = Router()
logger = logging.getLogger(__name__)

MAX_EXTRACTED_TEXT_LENGTH = 60000


def _limit_extracted_text(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_EXTRACTED_TEXT_LENGTH:
        return text, False

    return text[:MAX_EXTRACTED_TEXT_LENGTH].strip(), True


def _generate_session_id() -> str:
    return uuid.uuid4().hex[:12]


@router.message()
async def handle_message(message: types.Message) -> None:
    user_id = message.from_user.id

    await cleanup_session(user_id)

    if message.text and message.text.startswith("/"):
        await message.answer(UNKNOWN_COMMAND_TEXT)
        return

    usage_type = detect_input_usage_type(message)

    if not await can_process_input(user_id, usage_type):
        await message.answer(get_limit_reached_text(usage_type))
        return

    status_msg = await message.answer(ANALYZING_MATERIAL_TEXT)

    text = await extract_text_from_message(
        message=message,
        status_msg=status_msg
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
            user_id
        )
        await reply_with_voice(
            message,
            user_id,
            TEXT_SPLIT_ERROR,
            status_msg
        )
        return

    await save_document_history_from_message(
        user_id=user_id,
        message=message,
        text=text,
        chunks=chunks
    )

    await record_input_processed(user_id, usage_type)

    await set_reading_session(
        user_id=user_id,
        session={
            "session_id": _generate_session_id(),
            "chunks": chunks,
            "index": 0,
            "is_generating": True,
            "prefetch_task": None,
        }
    )

    if len(chunks) > 1:
        await reply_with_voice(
            message,
            user_id,
            build_large_text_split_text(len(chunks)),
            status_msg
        )
    else:
        await safe_delete_message(status_msg)

    try:
        await send_audio_chunk(message, user_id)

    finally:
        if await has_reading_session(user_id):
            await set_reading_session_generating(user_id, False)