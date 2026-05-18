# Файл: keyboards/settings.py

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

VOICE_CALLBACK_PREFIX = "voice:"
SPEED_CALLBACK_PREFIX = "speed:"
TTS_PROVIDER_CALLBACK_PREFIX = "tts_provider:"

VOICE_FEMALE_CALLBACK = f"{VOICE_CALLBACK_PREFIX}female"
VOICE_MALE_CALLBACK = f"{VOICE_CALLBACK_PREFIX}male"

SPEED_MINUS_25_CALLBACK = f"{SPEED_CALLBACK_PREFIX}-25%"
SPEED_NORMAL_CALLBACK = f"{SPEED_CALLBACK_PREFIX}+0%"
SPEED_PLUS_25_CALLBACK = f"{SPEED_CALLBACK_PREFIX}+25%"
SPEED_PLUS_50_CALLBACK = f"{SPEED_CALLBACK_PREFIX}+50%"

TTS_PROVIDER_PIPER_CALLBACK = f"{TTS_PROVIDER_CALLBACK_PREFIX}piper"
TTS_PROVIDER_EDGE_CALLBACK = f"{TTS_PROVIDER_CALLBACK_PREFIX}edge"


def settings_keyboard() -> InlineKeyboardMarkup:
    """
    Inline-клавіатура для налаштування голосу та швидкості читання.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="👩 Жіночий голос",
                callback_data=VOICE_FEMALE_CALLBACK
            ),
            InlineKeyboardButton(
                text="👨 Чоловічий голос",
                callback_data=VOICE_MALE_CALLBACK
            ),
        ],
        [
            InlineKeyboardButton(
                text="🐢 -0.25",
                callback_data=SPEED_MINUS_25_CALLBACK
            ),
            InlineKeyboardButton(
                text="⚡ 1 (Нормальна)",
                callback_data=SPEED_NORMAL_CALLBACK
            ),
        ],
        [
            InlineKeyboardButton(
                text="🚀 +0.25",
                callback_data=SPEED_PLUS_25_CALLBACK
            ),
            InlineKeyboardButton(
                text="🚀 +0.5",
                callback_data=SPEED_PLUS_50_CALLBACK
            ),
        ],
    ])
