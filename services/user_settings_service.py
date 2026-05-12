# Файл: services/user_settings_service.py

import logging

from config import DEFAULT_RATE, DEFAULT_VOICE
from database.db import get_user_settings, set_user_settings

logger = logging.getLogger(__name__)

SPEED_DISPLAY = {
    "-25%": "-0.25",
    "+0%": "1",
    "+25%": "+0.25",
    "+50%": "+0.5",
}

ALLOWED_SPEEDS = set(SPEED_DISPLAY.keys())


async def get_effective_user_settings(user_id: int) -> tuple[str, str]:
    """
    Повертає голос і швидкість користувача.

    Якщо в БД немає налаштувань, повертає дефолтні значення з config.
    """
    voice, rate = await get_user_settings(user_id)

    voice = voice or DEFAULT_VOICE
    rate = rate or DEFAULT_RATE

    return voice, rate


async def update_user_voice(user_id: int, voice: str) -> None:
    """
    Оновлює голос користувача.
    """
    if not voice or not voice.strip():
        logger.warning(
            "UserSettingsService: спроба встановити порожній voice для user_id=%s",
            user_id
        )
        raise ValueError("Voice cannot be empty.")

    await set_user_settings(user_id=user_id, voice=voice)


async def update_user_rate(user_id: int, rate: str) -> None:
    """
    Оновлює швидкість читання користувача.

    Додатково перевіряє, що швидкість входить у список дозволених значень.
    """
    if rate not in ALLOWED_SPEEDS:
        logger.warning(
            "UserSettingsService: невідоме значення rate для user_id=%s: %s",
            user_id,
            rate
        )
        raise ValueError(f"Unsupported rate value: {rate}")

    await set_user_settings(user_id=user_id, rate=rate)


def is_male_voice(voice: str) -> bool:
    """
    Визначає, чи голос є чоловічим.

    Зберігає поточну логіку проєкту:
    - Ostap або Guy — чоловічий голос;
    - усе інше — жіночий голос.
    """
    return "Ostap" in voice or "Guy" in voice


def get_voice_display_name(voice: str) -> str:
    """
    Повертає красиву назву голосу для UI.
    """
    return "👨 Чоловічий" if is_male_voice(voice) else "👩 Жіночий"


def get_rate_display(rate: str) -> str:
    """
    Повертає красиве відображення швидкості читання.
    """
    return SPEED_DISPLAY.get(rate, rate)