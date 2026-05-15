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
) -> None:
    """
    Надсилає список voice-файлів користувачу та видаляє їх після надсилання.

    caption і reply_markup додаються тільки до останнього voice-файлу,
    щоб не дублювати текст і кнопки під кожною частиною аудіо.
    """
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
        finally:
            safe_remove_file(audio_path)
