import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any


from keyboards.reading import (
    parse_reading_callback,
    summary_navigation_keyboard,
    summary_only_keyboard,
)
from services.document_history_service import (
    save_catalog_document_summary,
    save_catalog_document_summary_audio,
)
from services.parser import summarize_text_with_ai
from services.reading_service import (
    ReadingSession,
    cleanup_session,
    export_reading_audio,
    finish_reading_generation,
    get_current_reading_session,
    has_current_reading_session,
    reply_with_voice,
    safe_delete_message,
    send_audio_chunk,
    try_start_reading_generation,
    update_current_reading_session,
)
from services.tts import generate_voice
from services.usage_limits_service import (
    is_premium_user,
    refund_summary_generation,
    reserve_summary_generation,
)
from services.user_settings_service import (
    build_user_tts_provider_chain,
    get_effective_user_settings,
    get_effective_user_tts_provider,
)
from services.voice_selector import select_voice_for_text
from services.voice_sender import send_voice_file_ids, send_voice_files
from texts.limits import SUMMARY_LIMIT_REACHED_TEXT
from texts.messages import (
    EXPORT_AUDIO_ACCESS_DENIED_TEXT,
    EXPORT_AUDIO_GENERATION_ERROR,
    EXPORT_AUDIO_NOT_READY_TEXT,
    OUTDATED_READING_BUTTON_TEXT,
    READING_STOPPED_ALERT_TEXT,
    READING_STOPPED_MESSAGE_TEXT,
    SESSION_NOT_FOUND_OR_FINISHED_TEXT,
    SESSION_NOT_FOUND_TEXT,
    SUMMARY_AUDIO_GENERATION_ERROR,
    SUMMARY_ALREADY_READY_TEXT,
    SUMMARY_ALREADY_SENT_TEXT,
    SUMMARY_CAPTION_TEXT,
    SUMMARY_GENERATION_ERROR,
    SUMMARY_PREPARING_TEXT,
    SUMMARY_VOICE_PREPARING_TEXT,
    WAIT_AUDIO_PROCESSING_TEXT,
    WAIT_PROCESSING_TEXT,
)
from utils.text_checks import is_error_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReadingCallbackContext:
    user_id: int
    callback_session_id: str | None
    session: ReadingSession


def _callback_user_id(callback: Any) -> int | None:
    user = getattr(callback, "from_user", None)
    user_id = getattr(user, "id", None)

    return user_id if isinstance(user_id, int) else None

async def _refund_reserved_summary(user_id: int) -> None:
    try:
        await refund_summary_generation(user_id)
    except Exception:
        logger.exception(
            "ReadingCallbacks: failed to refund reserved summary usage user_id=%s",
            user_id,
        )


def _is_matching_session(
    session: ReadingSession,
    callback_session_id: str | None,
) -> bool:
    """
    Перевіряє, чи callback-кнопка належить до поточної reading session.

    callback_session_id=None залишає підтримку legacy-кнопок старого формату.
    """
    if callback_session_id is None:
        return True

    return session.get("session_id") == callback_session_id


def _reading_callback_identity(
    callback: Any,
) -> tuple[int, str | None] | None:
    user_id = _callback_user_id(callback)

    if user_id is None:
        return None

    _action, callback_session_id = parse_reading_callback(callback.data)

    return user_id, callback_session_id


async def _get_reading_callback_context(
    callback: Any,
    *,
    missing_text: str,
) -> ReadingCallbackContext | None:
    identity = _reading_callback_identity(callback)

    if identity is None:
        return None

    user_id, callback_session_id = identity
    session = await get_current_reading_session(user_id)

    if not session:
        await callback.answer(
            missing_text,
            show_alert=True,
        )
        return None

    if not _is_matching_session(session, callback_session_id):
        await callback.answer(
            OUTDATED_READING_BUTTON_TEXT,
            show_alert=True,
        )
        return None

    return ReadingCallbackContext(
        user_id=user_id,
        callback_session_id=callback_session_id,
        session=session,
    )


async def _safe_edit_reply_markup(
    callback: Any,
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


def _get_cached_summary_text(session: ReadingSession) -> str | None:
    summary_text = session.get("summary_text")

    if not isinstance(summary_text, str):
        return None

    summary_text = summary_text.strip()

    return summary_text or None


def _get_summary_voice_file_ids(session: ReadingSession) -> list[str]:
    file_ids = session.get("summary_voice_file_ids") or []

    if not isinstance(file_ids, list):
        return []

    return [str(file_id) for file_id in file_ids if str(file_id).strip()]


def _summary_voice_matches(
    session: ReadingSession,
    *,
    voice: str,
    rate: str,
    provider: str,
) -> bool:
    return (
        session.get("summary_voice_voice") == voice
        and session.get("summary_voice_rate") == rate
        and session.get("summary_voice_provider") == provider
    )


def _summary_has_next(session: ReadingSession) -> bool:
    chunks = session.get("chunks") or []
    current_index = int(session.get("index", 0))

    return current_index < len(chunks)


def _reading_is_complete(session: ReadingSession) -> bool:
    chunks = session.get("chunks") or []

    if not chunks:
        return False

    try:
        current_index = int(session.get("index", 0))
    except (TypeError, ValueError):
        return False

    return current_index >= len(chunks)


def _summary_keyboard(
    session: ReadingSession,
    callback_session_id: str | None,
):
    session_id = session.get("session_id", callback_session_id or "legacy")

    return summary_navigation_keyboard(
        has_next=_summary_has_next(session),
        session_id=session_id,
    )


async def _get_summary_audio_settings(
    user_id: int,
    summary_text: str,
) -> tuple[str, str, str]:
    voice_pref, rate = await get_effective_user_settings(user_id)
    provider = await get_effective_user_tts_provider(user_id)
    voice = select_voice_for_text(summary_text, voice_pref)

    return voice, rate, provider


def _get_catalog_document_id(
    user_id: int,
    session: ReadingSession,
) -> int | None:
    document_id = session.get("catalog_document_id")

    if document_id is None:
        return None

    try:
        return int(document_id)
    except (TypeError, ValueError):
        logger.warning(
            "ReadingCallbacks: invalid catalog_document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        return None


async def _save_session_summary_audio_to_catalog(
    user_id: int,
    session: ReadingSession,
    voice_file_ids: list[str],
    voice: str,
    rate: str,
    provider: str,
) -> None:
    document_id = _get_catalog_document_id(user_id, session)

    if document_id is None:
        return

    await save_catalog_document_summary_audio(
        user_id=user_id,
        document_id=document_id,
        voice_file_ids=voice_file_ids,
        voice=voice,
        rate=rate,
        provider=provider,
    )


async def _mark_summary_delivered(
    user_id: int,
    session: ReadingSession,
    *,
    voice_file_ids: list[str] | None = None,
    voice: str | None = None,
    rate: str | None = None,
    provider: str | None = None,
) -> None:
    updates = {
        "summary_delivered": True,
    }

    if voice_file_ids:
        updates.update({
            "summary_voice_file_ids": voice_file_ids,
            "summary_voice_voice": voice,
            "summary_voice_rate": rate,
            "summary_voice_provider": provider,
        })

    await update_current_reading_session(user_id, **updates)
    session.update(updates)


async def _send_cached_summary(
    callback: Any,
    user_id: int,
    session: ReadingSession,
    summary_text: str,
    already_delivered: bool,
    callback_session_id: str | None,
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

    if already_delivered:
        await _safe_edit_reply_markup(callback, reply_markup=None)
        await callback.answer(SUMMARY_ALREADY_SENT_TEXT, show_alert=True)
        return

    if not await try_start_reading_generation(user_id):
        await callback.answer(
            WAIT_PROCESSING_TEXT,
            show_alert=True,
        )
        return

    status_msg = None

    try:
        await callback.answer(SUMMARY_ALREADY_READY_TEXT)
        await _safe_edit_reply_markup(callback, reply_markup=None)

        voice, rate, provider = await _get_summary_audio_settings(
            user_id,
            summary_text,
        )
        keyboard = _summary_keyboard(session, callback_session_id)
        cached_file_ids = _get_summary_voice_file_ids(session)

        if cached_file_ids and _summary_voice_matches(
            session,
            voice=voice,
            rate=rate,
            provider=provider,
        ):
            sent_file_ids = await send_voice_file_ids(
                message=callback.message,
                voice_file_ids=cached_file_ids,
                caption=SUMMARY_CAPTION_TEXT,
                reply_markup=keyboard,
            ) or []

            if sent_file_ids:
                await _mark_summary_delivered(
                    user_id,
                    session,
                    voice_file_ids=sent_file_ids,
                    voice=voice,
                    rate=rate,
                    provider=provider,
                )
                await _save_session_summary_audio_to_catalog(
                    user_id,
                    session,
                    sent_file_ids,
                    voice,
                    rate,
                    provider,
                )
                return

        status_msg = await callback.message.answer(SUMMARY_VOICE_PREPARING_TEXT)

        audio_files = await generate_voice(
            text=summary_text,
            voice=voice,
            rate=rate,
            provider_chain=build_user_tts_provider_chain(
                provider,
                voice=voice,
            ),
            user_id=user_id,
        )

        if not audio_files:
            logger.warning(
                "ReadingCallbacks: TTS не створив cached summary audio "
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

        sent_file_ids = await send_voice_files(
            message=callback.message,
            audio_files=audio_files,
            caption=SUMMARY_CAPTION_TEXT,
            reply_markup=keyboard,
        ) or []

        if not sent_file_ids:
            logger.warning(
                "ReadingCallbacks: summary audio was generated but not delivered "
                "for user_id=%s",
                user_id,
            )

            await reply_with_voice(
                callback.message,
                user_id,
                SUMMARY_AUDIO_GENERATION_ERROR,
                status_msg,
            )
            return

        await _mark_summary_delivered(
            user_id,
            session,
            voice_file_ids=sent_file_ids,
            voice=voice,
            rate=rate,
            provider=provider,
        )
        await _save_session_summary_audio_to_catalog(
            user_id,
            session,
            sent_file_ids,
            voice,
            rate,
            provider,
        )

        await safe_delete_message(status_msg)

    except Exception:
        logger.exception(
            "ReadingCallbacks: помилка cached summary audio user_id=%s",
            user_id,
        )

        if callback.message:
            await reply_with_voice(
                callback.message,
                user_id,
                SUMMARY_AUDIO_GENERATION_ERROR,
                status_msg,
            )

    finally:
        if await has_current_reading_session(user_id):
            await finish_reading_generation(user_id)


async def _save_session_summary_to_catalog(
    user_id: int,
    session: ReadingSession,
    summary_text: str,
) -> None:
    document_id = _get_catalog_document_id(user_id, session)

    if document_id is None:
        return

    await save_catalog_document_summary(
        user_id=user_id,
        document_id=document_id,
        summary_text=summary_text,
    )


async def process_read_next(callback: Any) -> None:
    """
    Обробляє кнопку «Слухати далі».
    """
    context = await _get_reading_callback_context(
        callback,
        missing_text=SESSION_NOT_FOUND_OR_FINISHED_TEXT,
    )

    if context is None:
        return

    user_id = context.user_id
    callback_session_id = context.callback_session_id
    session = context.session

    show_summary_button = not bool(session.get("summary_delivered"))

    if not await try_start_reading_generation(user_id):
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
                can_export_audio=False,
                show_summary_button=show_summary_button,
            ),
        )
    else:
        await _safe_edit_reply_markup(callback, reply_markup=None)

    if not callback.message:
        if await has_current_reading_session(user_id):
            await finish_reading_generation(user_id)
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

        if await has_current_reading_session(user_id):
            await finish_reading_generation(user_id)


async def process_read_summary(callback: Any) -> None:
    """
    Обробляє кнопку «Короткий зміст».
    """
    context = await _get_reading_callback_context(
        callback,
        missing_text=SESSION_NOT_FOUND_TEXT,
    )

    if context is None:
        return

    user_id = context.user_id
    callback_session_id = context.callback_session_id
    session = context.session

    cached_summary_text = _get_cached_summary_text(session)

    if cached_summary_text:
        await _send_cached_summary(
            callback,
            user_id,
            session,
            cached_summary_text,
            already_delivered=bool(session.get("summary_delivered")),
            callback_session_id=callback_session_id,
        )
        return

    if not await try_start_reading_generation(user_id):
        await callback.answer(
            WAIT_PROCESSING_TEXT,
            show_alert=True,
        )
        return

    status_msg = None
    callback_answered = False
    summary_reserved = False

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

        summary_reserved = True

        await callback.answer()
        callback_answered = True

        await _safe_edit_reply_markup(callback, reply_markup=None)

        status_msg = await callback.message.answer(SUMMARY_PREPARING_TEXT)

        full_text = "\n\n".join(chunks)
        summary_text = await summarize_text_with_ai(full_text)

        if not summary_text or is_error_text(summary_text):
            await _refund_reserved_summary(user_id)
            summary_reserved = False
            await reply_with_voice(
                callback.message,
                user_id,
                summary_text or SUMMARY_GENERATION_ERROR,
                status_msg,
            )
            return

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
            user_id=user_id,
        )

        if not audio_files:
            logger.warning(
                "ReadingCallbacks: TTS не створив summary audio "
                "для user_id=%s",
                user_id,
            )

            await _refund_reserved_summary(user_id)
            summary_reserved = False
            await reply_with_voice(
                callback.message,
                user_id,
                SUMMARY_AUDIO_GENERATION_ERROR,
                status_msg,
            )
            return

        keyboard = _summary_keyboard(session, callback_session_id)

        sent_file_ids = await send_voice_files(
            message=callback.message,
            audio_files=audio_files,
            caption=SUMMARY_CAPTION_TEXT,
            reply_markup=keyboard,
        ) or []

        if not sent_file_ids:
            logger.warning(
                "ReadingCallbacks: summary audio was generated but not delivered "
                "for user_id=%s",
                user_id,
            )

            await _refund_reserved_summary(user_id)
            summary_reserved = False
            await reply_with_voice(
                callback.message,
                user_id,
                SUMMARY_AUDIO_GENERATION_ERROR,
                status_msg,
            )
            return

        summary_reserved = False

        await update_current_reading_session(
            user_id,
            summary_text=summary_text,
            summary_delivered=False,
        )
        session["summary_text"] = summary_text
        session["summary_delivered"] = False
        await _save_session_summary_to_catalog(user_id, session, summary_text)

        await _mark_summary_delivered(
            user_id,
            session,
            voice_file_ids=sent_file_ids,
            voice=voice,
            rate=rate,
            provider=tts_provider,
        )
        await _save_session_summary_audio_to_catalog(
            user_id,
            session,
            sent_file_ids,
            voice,
            rate,
            tts_provider,
        )

        summary_reserved = False
        await safe_delete_message(status_msg)

    except Exception:
        if summary_reserved:
            await _refund_reserved_summary(user_id)
            summary_reserved = False

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
        if await has_current_reading_session(user_id):
            await finish_reading_generation(user_id)


async def process_read_export_audio(callback: Any) -> None:
    context = await _get_reading_callback_context(
        callback,
        missing_text=SESSION_NOT_FOUND_TEXT,
    )

    if context is None:
        return

    user_id = context.user_id
    callback_session_id = context.callback_session_id

    if not await is_premium_user(user_id):
        await callback.answer(
            EXPORT_AUDIO_ACCESS_DENIED_TEXT,
            show_alert=True,
        )
        return

    if not _reading_is_complete(context.session):
        await callback.answer(
            EXPORT_AUDIO_NOT_READY_TEXT,
            show_alert=True,
        )
        return

    if not await try_start_reading_generation(user_id):
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

        if await has_current_reading_session(user_id):
            await finish_reading_generation(user_id)

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

        if await has_current_reading_session(user_id):
            await finish_reading_generation(user_id)

        await callback.message.answer(EXPORT_AUDIO_GENERATION_ERROR)


async def process_read_stop(callback: Any) -> None:
    """
    Обробляє кнопку «Закінчити».
    """
    identity = _reading_callback_identity(callback)

    if identity is None:
        return

    user_id, callback_session_id = identity

    session = await get_current_reading_session(user_id)

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
