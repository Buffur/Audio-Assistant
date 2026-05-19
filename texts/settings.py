# Файл: texts/settings.py

FEMALE_VOICE_CONFIRM_TEXT = "Встановлено жіночий голос для всіх мов."
MALE_VOICE_CONFIRM_TEXT = "Встановлено чоловічий голос для всіх мов."

UNKNOWN_VOICE_OPTION_TEXT = "❌ Невідомий варіант голосу."
UNKNOWN_SPEED_OPTION_TEXT = "❌ Невідоме значення швидкості."
UNKNOWN_TTS_PROVIDER_OPTION_TEXT = "❌ Невідомий варіант озвучки."

VOICE_UPDATE_ERROR_TEXT = "❌ Не вдалося змінити голос."
RATE_UPDATE_ERROR_TEXT = "❌ Не вдалося змінити швидкість."
TTS_PROVIDER_UPDATE_ERROR_TEXT = "❌ Не вдалося змінити озвучку."


def build_settings_text(
    voice_text: str,
    rate_text: str,
    tts_provider_text: str = "",
) -> str:
    """
    Формує текст повідомлення з поточними налаштуваннями користувача.
    """
    return (
        f"⚙️ Поточні налаштування:\n\n"
        f"🎤 Голос: {voice_text} (мова визначається автоматично)\n"
        f"⚡ Швидкість: {rate_text}\n\n"
        f"Оберіть нові параметри:"
    )


def build_speed_confirm_text(display_rate: str) -> str:
    """
    Формує текст підтвердження зміни швидкості читання.
    """
    return f"Швидкість читання встановлено на {display_rate}"


def build_tts_provider_confirm_text(display_provider: str) -> str:
    """
    Формує текст підтвердження зміни provider озвучки.
    """
    return f"Озвучку встановлено через {display_provider}"
