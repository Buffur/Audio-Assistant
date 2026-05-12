# Файл: services/voice_sender.py

import logging
import os

from aiogram import types
from aiogram.types import FSInputFile, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


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
    reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """
    Надсилає список voice-файлів користувачу та видаляє їх після надсилання.

    caption і reply_markup додаються тільки до останнього voice-файлу,
    щоб не дублювати текст і кнопки під кожною частиною аудіо.
    """
    for index, audio_path in enumerate(audio_files):
        is_last_file = index == len(audio_files) - 1

        try:
            await message.answer_voice(
                FSInputFile(audio_path),
                caption=caption if is_last_file else None,
                reply_markup=reply_markup if is_last_file else None
            )
        finally:
            safe_remove_file(audio_path)