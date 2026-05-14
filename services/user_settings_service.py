# Файл: services/user_settings_service.py

import logging

from config import DEFAULT_RATE, DEFAULT_VOICE
from database.db import (
    get_user_settings,
    get_user_tts_provider,
    set_user_settings,
    set_user_tts_provider,
)
from services.piper_tts import is_piper_voice_configured
from services.usage_limits_service import is_premium_user

logger = logging.getLogger(__name__)

SPEED_DISPLAY = {
    "-25%": "-0.25",
    "+0%": "1",
    "+25%": "+0.25",
    "+50%": "+0.5",
}

ALLOWED_SPEEDS = set(SPEED_DISPLAY.keys())

DEFAULT_USER_TTS_PROVIDER = "edge"

TTS_PROVIDER_DISPLAY = {
    "edge": "Edge",
    "piper": "Piper (локально)",
    "gemini": "Gemini (Ліміт+)",
}

ALLOWED_USER_TTS_PROVIDERS = {"edge", "piper"}


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


async def get_effective_user_tts_provider(user_id: int) -> str:
    """
    Повертає TTS provider користувача.

    Для Ліміт+ примусово використовуємо Gemini з fallback-ланцюжком нижче.
    Для звичайних користувачів дефолт — Edge, Piper лишається ручним вибором.
    """
    if await is_premium_user(user_id):
        return "gemini"

    tts_provider = await get_user_tts_provider(user_id)

    if tts_provider in ALLOWED_USER_TTS_PROVIDERS:
        return tts_provider

    return DEFAULT_USER_TTS_PROVIDER


async def update_user_tts_provider(user_id: int, tts_provider: str) -> None:
    """
    Оновлює provider озвучки користувача.
    """
    if tts_provider not in ALLOWED_USER_TTS_PROVIDERS:
        logger.warning(
            "UserSettingsService: невідомий TTS provider для user_id=%s: %s",
            user_id,
            tts_provider,
        )
        raise ValueError(f"Unsupported TTS provider: {tts_provider}")

    await set_user_tts_provider(user_id=user_id, tts_provider=tts_provider)


def build_user_tts_provider_chain(
    tts_provider: str,
    voice: str | None = None,
) -> list[str]:
    """
    Формує fallback-ланцюжок для користувацької озвучки.
    """
    piper_available = voice is None or is_piper_voice_configured(voice)

    if tts_provider == "gemini":
        providers = ["gemini", "edge"]

        if piper_available:
            providers.append("piper")

        return providers

    if tts_provider == "edge":
        providers = ["edge"]

        if piper_available:
            providers.append("piper")

        return providers

    if not piper_available:
        return ["edge"]

    return ["piper", "edge"]


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


def get_tts_provider_display(tts_provider: str) -> str:
    """
    Повертає красиву назву TTS provider для UI.
    """
    return TTS_PROVIDER_DISPLAY.get(tts_provider, tts_provider)
