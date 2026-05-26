# Файл: services/voice_selector.py

import logging

from langdetect import LangDetectException, detect

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "uk"
LANGUAGE_DETECTION_MAX_CHARS = 2_000

VOICES_BY_LANGUAGE = {
    "uk": {
        "male": "uk-UA-OstapNeural",
        "female": "uk-UA-PolinaNeural",
    },
    "en": {
        "male": "en-US-GuyNeural",
        "female": "en-US-JennyNeural",
    },
    "de": {
        "male": "de-DE-KillianNeural",
        "female": "de-DE-AmalaNeural",
    },
    "pl": {
        "male": "pl-PL-MarekNeural",
        "female": "pl-PL-ZofiaNeural",
    },
    "sk": {
        "male": "sk-SK-LukasNeural",
        "female": "sk-SK-ViktoriaNeural",
    },
    "cs": {
        "male": "cs-CZ-AntoninNeural",
        "female": "cs-CZ-VlastaNeural",
    },
}


def _language_detection_sample(text: str) -> str:
    return text.strip()[:LANGUAGE_DETECTION_MAX_CHARS]


def detect_text_language(text: str) -> str:
    """
    Визначає мову тексту.

    Якщо мову не вдалося визначити або вона не підтримується,
    повертає українську як дефолтну.
    """
    sample = _language_detection_sample(text)

    if not sample:
        return DEFAULT_LANGUAGE

    try:
        detected_language = detect(sample)
    except LangDetectException:
        logger.warning("VoiceSelector: не вдалося визначити мову тексту")
        return DEFAULT_LANGUAGE

    if detected_language not in VOICES_BY_LANGUAGE:
        logger.info(
            "VoiceSelector: мова '%s' не підтримується, використовую '%s'",
            detected_language,
            DEFAULT_LANGUAGE
        )
        return DEFAULT_LANGUAGE

    return detected_language


def get_voice_gender_from_preference(voice_pref: str) -> str:
    """
    Визначає стать голосу на основі поточного voice_pref.

    Зберігає стару логіку:
    - якщо в голосі є Ostap або Guy — вважаємо, що користувач обрав чоловічий голос;
    - інакше використовуємо жіночий голос.
    """
    if not voice_pref:
        return "female"

    is_male = "Ostap" in voice_pref or "Guy" in voice_pref

    return "male" if is_male else "female"


def select_voice_for_text(text: str, voice_pref: str) -> str:
    """
    Обирає TTS-голос для конкретного тексту.

    Враховує:
    - мову тексту;
    - поточну перевагу користувача: чоловічий або жіночий голос.
    """
    language = detect_text_language(text)
    gender = get_voice_gender_from_preference(voice_pref)

    return VOICES_BY_LANGUAGE[language][gender]
