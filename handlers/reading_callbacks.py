# Файл: handlers/reading_callbacks.py

import logging
from contextlib import suppress

from aiogram import F, Router, types

from keyboards.reading import (
    READ_EXPORT_AUDIO_ACTION,
    READ_NEXT_ACTION,
    READ_STOP_ACTION,
    READ_SUMMARY_ACTION,
    parse_reading_callback,
    summary_navigation_keyboard,
    summary_only_keyboard,
)
from services.document_history_service import save_catalog_document_summary
from services.parser import summarize_text_with_ai
from services.reading_service import (
    cleanup_session,
    export_reading_audio,
    reply_with_voice,
    safe_delete_message,
    send_audio_chunk,
)
from services.reading_session_store import (
    finish_generation,
    get_reading_session,
    has_reading_session,
    try_start_generation,
    update_reading_session,
)
from services.tts import generate_voice
from services.usage_limits_service import (
    is_premium_user,
    reserve_summary_generation,
)
from services.user_settings_service import (
    build_user_tts_provider_chain,
    get_effective_user_settings,
    get_effective_user_tts_provider,
)
from services.voice_selector import select_voice_for_text
from services.voice_sender import send_voice_files
from texts.limits import SUMMARY_LIMIT_REACHED_TEXT
from texts.messages import (
    EXPORT_AUDIO_ACCESS_DENIED_TEXT,
    EXPORT_AUDIO_GENERATION_ERROR,
    OUTDATED_READING_BUTTON_TEXT,
    READING_STOPPED_ALERT_TEXT,
    READING_STOPPED_MESSAGE_TEXT,
    SESSION_NOT_FOUND_OR_FINISHED_TEXT,
    SESSION_NOT_FOUND_TEXT,
    SUMMARY_AUDIO_GENERATION_ERROR,
    SUMMARY_ALREADY_READY_TEXT,
    SUMMARY_ALREADY_SENT_TEXT,
    SUMMARY_CACHED_TEXT_HEADER,
    SUMMARY_CAPTION_TEXT,
    SUMMARY_GENERATION_ERROR,
    SUMMARY_PREPARING_TEXT,
    WAIT_AUDIO_PROCESSING_TEXT,
    WAIT_PROCESSING_TEXT,
)
from utils.splitter import split_text
from utils.text_checks import is_error_text

router = Router()
logger = logging.getLogger(__name__)
CACHED_SUMMARY_MESSAGE_MAX_LENGTH = 3500


def _is_matching_session(
    session: dict,
    callback_session_id: str | None,
) -> bool:
    """
    Перевіряє, чи callback-кнопка належить до поточної reading session.

    callback_session_id=None залишає підтримку legacy-кнопок старого формату.
    """
    if callback_session_id is None:
        return True

    return session.get("session_id") == callback_session_id


async def _safe_edit_reply_markup(
    callback: types.CallbackQuery,
    reply_markup=None,
) -> None:
    """
    Безпечно редагує inline-клавіатуру.
    """
    if not callback.message:
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=reply_markup)
    except Exception:
        logger.exception(
            "ReadingCallbacks: не вдалося оновити reply_markup user_id=%s",
            callback.from_user.id if callback.from_user else None,
        )


def _get_cached_summary_text(session: dict) -> str | None:
    summary_text = session.get("summary_text")

    if not isinstance(summary_text, str):
        return None

    summary_text = summary_text.strip()

    return summary_text or None


async def _send_cached_summary(
    callback: types.CallbackQuery,
    user_id: int,
    summary_text: str,
    already_delivered: bool,
) -> None:
    if not callback.message:
        await callback.answer(
            (
                SUMMARY_ALREADY_SENT_TEXT
                if already_delivered
                else SUMMARY_ALREADY_READY_TEXT
            ),
            show_alert=True,
        )
        return

    await _safe_edit_reply_markup(callback, reply_markup=None)

    if already_delivered:
        await callback.answer(SUMMARY_ALREADY_SENT_TEXT, show_alert=True)
        return

    await callback.answer(SUMMARY_ALREADY_READY_TEXT)

    cached_text = f"{SUMMARY_CACHED_TEXT_HEADER}\n\n{summary_text}"

    for message_text in split_text(
        cached_text,
        max_length=CACHED_SUMMARY_MESSAGE_MAX_LENGTH,
    ):
        await callback.message.answer(message_text)

    await update_reading_session(user_id, summary_delivered=True)


async def _save_session_summary_to_catalog(
    user_id: int,
    session: dict,
    summary_text: str,
) -> None:
    document_id = session.get("catalog_document_id")

    if document_id is None:
        return

    try:
        document_id = int(document_id)
    except (TypeError, ValueError):
        logger.warning(
            "ReadingCallbacks: invalid catalog_document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        return

    await save_catalog_document_summary(
        user_id=user_id,
        document_id=document_id,
        summary_text=summary_text,
    )


@router.callback_query(F.data.startswith(READ_NEXT_ACTION))
async def process_read_next(callback: types.CallbackQuery) -> None:
    """
    Обробляє кнопку «Слухати далі».
    """
    user_id = callback.from_user.id
    _, callback_session_id = parse_reading_callback(callback.data)

    session = await get_reading_session(user_id)

    if not session:
        await callback.answer(
            SESSION_NOT_FOUND_OR_FINISHED_TEXT,
            show_alert=True,
        )
        return

    if not _is_matching_session(session, callback_session_id):
        await callback.answer(
            OUTDATED_READING_BUTTON_TEXT,
            show_alert=True,
        )
        return

    show_summary_button = not bool(session.get("summary_delivered"))

    if not await try_start_generation(user_id):
        await callback.answer(
            WAIT_AUDIO_PROCESSING_TEXT,
            show_alert=True,
        )
        return

    await callback.answer()

    if callback_session_id:
        await _safe_edit_reply_markup(
            callback,
            reply_markup=summary_only_keyboard(
                callback_session_id,
                can_export_audio=await is_premium_user(user_id),
                show_summary_button=show_summary_button,
            ),
        )
    else:
        await _safe_edit_reply_markup(callback, reply_markup=None)

    if not callback.message:
        if await has_reading_session(user_id):
            await finish_generation(user_id)
        return

    try:
        await send_audio_chunk(callback.message, user_id)

    except Exception:
        logger.exception(
            "ReadingCallbacks: помилка під час надсилання наступної "
            "частини user_id=%s",
            user_id,
        )

        if callback.message:
            await callback.message.answer(
                "❌ Сталася помилка під час генерації наступної частини."
            )

        if await has_reading_session(user_id):
            await finish_generation(user_id)


@router.callback_query(F.data.startswith(READ_SUMMARY_ACTION))
async def process_read_summary(callback: types.CallbackQuery) -> None:
    """
    Обробляє кнопку «Короткий зміст».
    """
    user_id = callback.from_user.id
    _, callback_session_id = parse_reading_callback(callback.data)

    session = await get_reading_session(user_id)

    if not session:
        await callback.answer(
            SESSION_NOT_FOUND_TEXT,
            show_alert=True,
        )
        return

    if not _is_matching_session(session, callback_session_id):
        await callback.answer(
            OUTDATED_READING_BUTTON_TEXT,
            show_alert=True,
        )
        return

    cached_summary_text = _get_cached_summary_text(session)

    if cached_summary_text:
        await _send_cached_summary(
            callback,
            user_id,
            cached_summary_text,
            already_delivered=bool(session.get("summary_delivered")),
        )
        return

    if not await try_start_generation(user_id):
        await callback.answer(
            WAIT_PROCESSING_TEXT,
            show_alert=True,
        )
        return

    status_msg = None
    callback_answered = False

    try:
        if not callback.message:
            await callback.answer(
                SESSION_NOT_FOUND_TEXT,
                show_alert=True,
            )
            callback_answered = True

            logger.warning(
                "ReadingCallbacks: callback.message відсутній для summary "
                "user_id=%s",
                user_id,
            )
            return

        chunks = session.get("chunks") or []

        if not chunks:
            await callback.answer()
            callback_answered = True

            status_msg = await callback.message.answer(SUMMARY_PREPARING_TEXT)

            await reply_with_voice(
                callback.message,
                user_id,
                SESSION_NOT_FOUND_TEXT,
                status_msg,
            )
            return

        if not await reserve_summary_generation(user_id):
            await callback.answer(
                SUMMARY_LIMIT_REACHED_TEXT,
                show_alert=True,
            )
            callback_answered = True
            return

        await callback.answer()
        callback_answered = True

        await _safe_edit_reply_markup(callback, reply_markup=None)

        status_msg = await callback.message.answer(SUMMARY_PREPARING_TEXT)

        full_text = "\n\n".join(chunks)
        summary_text = await summarize_text_with_ai(full_text)

        if not summary_text or is_error_text(summary_text):
            await reply_with_voice(
                callback.message,
                user_id,
                summary_text or SUMMARY_GENERATION_ERROR,
                status_msg,
            )
            return

        await update_reading_session(
            user_id,
            summary_text=summary_text,
            summary_delivered=False,
        )
        session["summary_text"] = summary_text
        session["summary_delivered"] = False
        await _save_session_summary_to_catalog(user_id, session, summary_text)

        voice_pref, rate = await get_effective_user_settings(user_id)
        tts_provider = await get_effective_user_tts_provider(user_id)
        voice = select_voice_for_text(summary_text, voice_pref)

        audio_files = await generate_voice(
            text=summary_text,
            voice=voice,
            rate=rate,
            provider_chain=build_user_tts_provider_chain(
                tts_provider,
                voice=voice,
            ),
        )

        if not audio_files:
            logger.warning(
                "ReadingCallbacks: TTS не створив summary audio "
                "для user_id=%s",
                user_id,
            )

            await reply_with_voice(
                callback.message,
                user_id,
                SUMMARY_AUDIO_GENERATION_ERROR,
                status_msg,
            )
            return

        current_index = int(session.get("index", 0))
        has_next = current_index < len(chunks)
        session_id = session.get("session_id", callback_session_id or "legacy")

        keyboard = summary_navigation_keyboard(
            has_next=has_next,
            session_id=session_id,
        )

        await send_voice_files(
            message=callback.message,
            audio_files=audio_files,
            caption=SUMMARY_CAPTION_TEXT,
            reply_markup=keyboard,
        )

        await update_reading_session(user_id, summary_delivered=True)
        session["summary_delivered"] = True

        await safe_delete_message(status_msg)

    except Exception:
        logger.exception(
            "ReadingCallbacks: помилка генерації короткого змісту user_id=%s",
            user_id,
        )

        if not callback_answered:
            with suppress(Exception):
                await callback.answer(
                    SUMMARY_GENERATION_ERROR,
                    show_alert=True,
                )

        if callback.message:
            await reply_with_voice(
                callback.message,
                user_id,
                SUMMARY_GENERATION_ERROR,
                status_msg,
            )

    finally:
        if await has_reading_session(user_id):
            await finish_generation(user_id)


@router.callback_query(F.data.startswith(READ_EXPORT_AUDIO_ACTION))
async def process_read_export_audio(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    _, callback_session_id = parse_reading_callback(callback.data)

    session = await get_reading_session(user_id)

    if not session:
        await callback.answer(
            SESSION_NOT_FOUND_TEXT,
            show_alert=True,
        )
        return

    if not _is_matching_session(session, callback_session_id):
        await callback.answer(
            OUTDATED_READING_BUTTON_TEXT,
            show_alert=True,
        )
        return

    if not await is_premium_user(user_id):
        await callback.answer(
            EXPORT_AUDIO_ACCESS_DENIED_TEXT,
            show_alert=True,
        )
        return

    if not await try_start_generation(user_id):
        await callback.answer(
            WAIT_AUDIO_PROCESSING_TEXT,
            show_alert=True,
        )
        return

    if not callback.message:
        await callback.answer(
            SESSION_NOT_FOUND_TEXT,
            show_alert=True,
        )

        if await has_reading_session(user_id):
            await finish_generation(user_id)

        return

    await callback.answer()

    try:
        await export_reading_audio(
            callback.message,
            user_id,
            expected_session_id=callback_session_id,
        )
    except Exception:
        logger.exception(
            "ReadingCallbacks: error while queueing full audio export user_id=%s",
            user_id,
        )

        if await has_reading_session(user_id):
            await finish_generation(user_id)

        await callback.message.answer(EXPORT_AUDIO_GENERATION_ERROR)


@router.callback_query(F.data.startswith(READ_STOP_ACTION))
async def process_read_stop(callback: types.CallbackQuery) -> None:
    """
    Обробляє кнопку «Закінчити».
    """
    user_id = callback.from_user.id
    _, callback_session_id = parse_reading_callback(callback.data)

    session = await get_reading_session(user_id)

    if session and not _is_matching_session(session, callback_session_id):
        await callback.answer(
            OUTDATED_READING_BUTTON_TEXT,
            show_alert=True,
        )
        return

    await cleanup_session(user_id)
    await _safe_edit_reply_markup(callback, reply_markup=None)

    await callback.answer(READING_STOPPED_ALERT_TEXT)

    if callback.message:
        await callback.message.answer(READING_STOPPED_MESSAGE_TEXT)
