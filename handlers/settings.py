# Файл: handlers/settings.py

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from handlers.callback_guards import callback_user_id, message_user_id
from keyboards.main import SETTINGS_BUTTON_TEXT
from keyboards.settings import (
    SETTINGS_PREVIEW_CALLBACK,
    SPEED_CALLBACK_PREFIX,
    VOICE_CALLBACK_PREFIX,
    settings_keyboard,
)
from services.tts import generate_voice
from services.user_settings_service import (
    ALLOWED_SPEEDS,
    build_user_tts_provider_chain,
    get_effective_user_settings,
    get_effective_user_tts_provider,
    get_rate_display,
    get_voice_display_name,
    update_user_rate,
    update_user_voice,
)
from services.voice_sender import send_voice_files
from texts.settings import (
    FEMALE_VOICE_CONFIRM_TEXT,
    MALE_VOICE_CONFIRM_TEXT,
    RATE_UPDATE_ERROR_TEXT,
    SETTINGS_PREVIEW_PREPARING_TEXT,
    SETTINGS_PREVIEW_TEXT,
    UNKNOWN_SPEED_OPTION_TEXT,
    UNKNOWN_VOICE_OPTION_TEXT,
    VOICE_UPDATE_ERROR_TEXT,
    build_settings_text,
    build_speed_confirm_text,
)

router = Router()
logger = logging.getLogger(__name__)

VOICE_OPTIONS = {
    "female": {
        "voice": "uk-UA-PolinaNeural",
        "confirm_text": FEMALE_VOICE_CONFIRM_TEXT,
    },
    "male": {
        "voice": "uk-UA-OstapNeural",
        "confirm_text": MALE_VOICE_CONFIRM_TEXT,
    },
}


async def get_settings_text(user_id: int) -> str:
    """
    Генерує актуальний текст повідомлення з налаштуваннями.
    """
    voice, rate = await get_effective_user_settings(user_id)

    voice_text = get_voice_display_name(voice)
    rate_text = get_rate_display(rate)

    return build_settings_text(
        voice_text=voice_text,
        rate_text=rate_text,
    )


async def _safe_edit_settings_message(callback: CallbackQuery, user_id: int) -> None:
    """
    Безпечно оновлює повідомлення з налаштуваннями.

    Якщо Telegram не дозволяє редагувати повідомлення
    або текст не змінився, помилка логується, але не ламає сценарій.
    """
    if callback.message is None:
        return

    new_text = await get_settings_text(user_id)

    try:
        await callback.message.edit_text(
            new_text,
            reply_markup=settings_keyboard()
        )
    except Exception:
        logger.exception(
            "Не вдалося оновити повідомлення налаштувань для user_id=%s",
            user_id
        )


async def _send_voice_preview(
    callback: CallbackQuery,
    text: str,
    voice: str,
    rate: str,
    tts_provider: str,
) -> None:
    """
    Генерує та надсилає голосове прев'ю налаштувань.

    Якщо генерація не вдалася, користувач отримує текстове повідомлення,
    а помилка потрапляє в логи.
    """
    if callback.message is None:
        await callback.answer(SETTINGS_PREVIEW_TEXT, show_alert=True)
        return

    try:
        audio_files = await generate_voice(
            text=text,
            voice=voice,
            rate=rate,
            provider_chain=build_user_tts_provider_chain(
                tts_provider,
                voice=voice,
            ),
        )

        if not audio_files:
            logger.warning(
                "TTS preview не створив жодного аудіофайлу для user_id=%s",
                callback_user_id(callback)
            )
            await callback.message.answer(text)
            return

        await send_voice_files(
            message=callback.message,
            audio_files=audio_files
        )

    except Exception:
        logger.exception(
            "Помилка генерації голосового прев'ю для user_id=%s",
            callback_user_id(callback)
        )
        await callback.message.answer(text)


@router.message(Command("settings"))
@router.message(F.text == SETTINGS_BUTTON_TEXT)
async def settings_handler(message: Message) -> None:
    user_id = message_user_id(message)

    if user_id is None:
        return

    text = await get_settings_text(user_id)
    await message.answer(text, reply_markup=settings_keyboard())


@router.callback_query(F.data.startswith(VOICE_CALLBACK_PREFIX))
async def change_voice(callback: CallbackQuery) -> None:
    user_id = callback_user_id(callback)

    if user_id is None:
        return

    _, _, voice_key = callback.data.partition(":")

    option = VOICE_OPTIONS.get(voice_key)
    if not option:
        logger.warning(
            "Отримано невідомий voice callback від user_id=%s: %s",
            user_id,
            callback.data
        )
        await callback.answer(UNKNOWN_VOICE_OPTION_TEXT, show_alert=True)
        return

    voice = option["voice"]
    text_confirm = option["confirm_text"]

    try:
        await update_user_voice(user_id=user_id, voice=voice)
    except ValueError:
        logger.exception(
            "Не вдалося оновити голос для user_id=%s",
            user_id
        )
        await callback.answer(VOICE_UPDATE_ERROR_TEXT, show_alert=True)
        return

    await callback.answer(text_confirm)

    await _safe_edit_settings_message(callback, user_id)


@router.callback_query(F.data.startswith(SPEED_CALLBACK_PREFIX))
async def change_speed(callback: CallbackQuery) -> None:
    user_id = callback_user_id(callback)

    if user_id is None:
        return

    _, _, rate = callback.data.partition(":")

    if rate not in ALLOWED_SPEEDS:
        logger.warning(
            "Отримано невідомий speed callback від user_id=%s: %s",
            user_id,
            callback.data
        )
        await callback.answer(UNKNOWN_SPEED_OPTION_TEXT, show_alert=True)
        return

    try:
        await update_user_rate(user_id=user_id, rate=rate)
    except ValueError:
        logger.exception(
            "Не вдалося оновити швидкість для user_id=%s: %s",
            user_id,
            rate
        )
        await callback.answer(RATE_UPDATE_ERROR_TEXT, show_alert=True)
        return

    display_rate = get_rate_display(rate)
    text_confirm = build_speed_confirm_text(display_rate)

    await callback.answer(text_confirm)

    await _safe_edit_settings_message(callback, user_id)


@router.callback_query(F.data == SETTINGS_PREVIEW_CALLBACK)
async def settings_preview(callback: CallbackQuery) -> None:
    user_id = callback_user_id(callback)

    if user_id is None:
        return

    voice, rate = await get_effective_user_settings(user_id)
    tts_provider = await get_effective_user_tts_provider(user_id)

    await callback.answer(SETTINGS_PREVIEW_PREPARING_TEXT)

    await _send_voice_preview(
        callback=callback,
        text=SETTINGS_PREVIEW_TEXT,
        voice=voice,
        rate=rate,
        tts_provider=tts_provider,
    )
