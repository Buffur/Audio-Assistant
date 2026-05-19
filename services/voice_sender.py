# Файл: services/voice_sender.py

import logging
import os
from collections.abc import Callable

from aiogram import types
from aiogram.types import FSInputFile, InlineKeyboardMarkup

from services.telegram_sender import DEFAULT_SEND_DELAY_SECONDS, safe_answer_voice

logger = logging.getLogger(__name__)

SEND_VOICE_DELAY_SECONDS = DEFAULT_SEND_DELAY_SECONDS

VoiceCaptionBuilder = Callable[[int, int, str | None], str | None]


def safe_remove_file(file_path: str | None) -> None:
    """
    Безпечно видаляє тимчасовий файл.

    Помилка видалення не повинна ламати роботу бота,
    але має бути записана в логи.
    """
    if not file_path:
        return

    if not os.path.exists(file_path):
        return

    try:
        os.remove(file_path)
        logger.debug("VoiceSender: тимчасовий файл видалено: %s", file_path)
    except OSError:
        logger.exception(
            "VoiceSender: не вдалося видалити тимчасовий файл: %s",
            file_path
        )


async def send_voice_files(
    message: types.Message,
    audio_files: list[str],
    caption: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    caption_builder: VoiceCaptionBuilder | None = None,
) -> list[str]:
    """
    Надсилає список voice-файлів користувачу та видаляє їх після надсилання.

    caption і reply_markup додаються тільки до останнього voice-файлу,
    щоб не дублювати текст і кнопки під кожною частиною аудіо.
    """
    sent_file_ids: list[str] = []

    for index, audio_path in enumerate(audio_files):
        is_last_file = index == len(audio_files) - 1
        file_number = index + 1
        files_count = len(audio_files)
        voice_caption = caption if is_last_file else None

        if caption_builder is not None:
            voice_caption = caption_builder(file_number, files_count, caption)

        try:
            sent_message = await safe_answer_voice(
                message=message,
                voice=FSInputFile(audio_path),
                caption=voice_caption,
                reply_markup=reply_markup if is_last_file else None,
                delay_seconds=SEND_VOICE_DELAY_SECONDS,
            )

            if sent_message is None:
                logger.warning(
                    "VoiceSender: не вдалося надіслати voice-файл: %s",
                    audio_path,
                )
            else:
                voice = getattr(sent_message, "voice", None)
                file_id = getattr(voice, "file_id", None)

                if file_id:
                    sent_file_ids.append(str(file_id))
        finally:
            safe_remove_file(audio_path)

    return sent_file_ids


async def send_voice_file_ids(
    message: types.Message,
    voice_file_ids: list[str],
    caption: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> list[str]:
    """
    Повторно надсилає voice-повідомлення за Telegram file_id.

    file_id — це вже завантажений у Telegram файл, тому локальний файл
    повторно створювати або видаляти не потрібно.
    """
    sent_file_ids: list[str] = []

    for index, file_id in enumerate(voice_file_ids):
        is_last_file = index == len(voice_file_ids) - 1

        sent_message = await safe_answer_voice(
            message=message,
            voice=file_id,
            caption=caption if is_last_file else None,
            reply_markup=reply_markup if is_last_file else None,
            delay_seconds=SEND_VOICE_DELAY_SECONDS,
        )

        if sent_message is None:
            logger.warning(
                "VoiceSender: не вдалося надіслати cached voice file_id: %s",
                file_id,
            )
            continue

        voice = getattr(sent_message, "voice", None)
        returned_file_id = getattr(voice, "file_id", None)
        sent_file_ids.append(str(returned_file_id or file_id))

    return sent_file_ids
