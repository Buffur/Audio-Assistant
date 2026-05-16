# Файл: services/gemini_tts.py

import asyncio
import base64
import logging
import os
import wave

from google.genai import types

from config import (
    GEMINI_TTS_FEMALE_VOICE,
    GEMINI_TTS_MALE_VOICE,
    GEMINI_TTS_MODEL,
    GEMINI_TTS_MODEL_CHAIN,
    GEMINI_TTS_REQUEST_TIMEOUT_SECONDS,
    GEMINI_TTS_STYLE_PROMPT,
    GEMINI_TTS_VOICE,
)
from services.gemini_client import (
    generate_gemini_content_with_fallback,
    normalize_model_chain,
)
from utils.audio import convert_to_ogg, create_temp_file_path, safe_remove_file

logger = logging.getLogger(__name__)

GEMINI_TTS_SAMPLE_RATE = 24000
GEMINI_TTS_CHANNELS = 1
GEMINI_TTS_SAMPLE_WIDTH = 2
GEMINI_TTS_CONTINUITY_PROMPT = (
    "Maintain the same voice, pace, and neutral newsroom intonation across "
    "chunks. Treat this chunk as part of one continuous article and do not "
    "restart the emotional tone."
)

GEMINI_TTS_MALE_VOICE_MARKERS = {
    "antonin",
    "conrad",
    "guy",
    "killian",
    "lukas",
    "marek",
    "ostap",
}

def _rate_instruction(rate: str) -> str:
    if rate == "-25%":
        return "Use a slightly slower pace."

    if rate == "+25%":
        return "Use a slightly faster pace."

    if rate == "+50%":
        return "Use a fast but still clear pace."

    return "Use a natural pace."


def get_gemini_tts_voice(edge_voice: str) -> str:
    voice_lower = (edge_voice or "").lower()

    if any(marker in voice_lower for marker in GEMINI_TTS_MALE_VOICE_MARKERS):
        return GEMINI_TTS_MALE_VOICE.strip() or GEMINI_TTS_VOICE

    return GEMINI_TTS_FEMALE_VOICE.strip() or GEMINI_TTS_VOICE


def _build_gemini_tts_prompt(text: str, rate: str) -> str:
    style_prompt = GEMINI_TTS_STYLE_PROMPT.strip()
    rate_prompt = _rate_instruction(rate)
    prompt_parts = [
        part for part in (
            style_prompt,
            GEMINI_TTS_CONTINUITY_PROMPT,
            rate_prompt,
        )
        if part
    ]

    return f"{' '.join(prompt_parts)}\n\n{text}"


def gemini_tts_model_chain() -> list[str]:
    return normalize_model_chain(
        primary_model=GEMINI_TTS_MODEL,
        fallback_models=GEMINI_TTS_MODEL_CHAIN,
    )


def _extract_audio_data(response) -> bytes:
    try:
        data = response.candidates[0].content.parts[0].inline_data.data
    except (AttributeError, IndexError, TypeError) as error:
        raise RuntimeError("Gemini TTS не повернув audio payload.") from error

    if not data:
        raise RuntimeError("Gemini TTS повернув порожній audio payload.")

    if isinstance(data, str):
        return base64.b64decode(data)

    return bytes(data)


def _write_pcm_to_wav(
    *,
    pcm_data: bytes,
    wav_path: str,
) -> None:
    with wave.open(wav_path, "wb") as wav_file:
        wav_file.setnchannels(GEMINI_TTS_CHANNELS)
        wav_file.setsampwidth(GEMINI_TTS_SAMPLE_WIDTH)
        wav_file.setframerate(GEMINI_TTS_SAMPLE_RATE)
        wav_file.writeframes(pcm_data)

    if not os.path.exists(wav_path) or os.path.getsize(wav_path) == 0:
        raise RuntimeError("Gemini TTS не створив коректний WAV-файл.")


async def generate_gemini_tts_ogg(
    *,
    text: str,
    voice: str,
    rate: str,
    chunk_index: int,
    chunks_count: int,
) -> str:
    """
    Генерує OGG/Opus voice-файл через Gemini TTS.

    Gemini TTS повертає PCM 24kHz mono, тому спочатку пакуємо PCM у WAV,
    а потім конвертуємо WAV в OGG/Opus для Telegram voice.
    """
    wav_path = create_temp_file_path(".wav")
    gemini_voice = get_gemini_tts_voice(voice)

    try:
        logger.info(
            "GeminiTTS: генерація chunk=%s/%s, models=%s, voice=%s, text_length=%s",
            chunk_index,
            chunks_count,
            ",".join(gemini_tts_model_chain()),
            gemini_voice,
            len(text),
        )

        response = await generate_gemini_content_with_fallback(
            primary_model=GEMINI_TTS_MODEL,
            fallback_models=GEMINI_TTS_MODEL_CHAIN,
            contents=_build_gemini_tts_prompt(text, rate),
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=gemini_voice,
                        )
                    )
                ),
            ),
            context="tts",
            timeout_seconds=GEMINI_TTS_REQUEST_TIMEOUT_SECONDS,
        )

        pcm_data = _extract_audio_data(response)

        await asyncio.to_thread(
            _write_pcm_to_wav,
            pcm_data=pcm_data,
            wav_path=wav_path,
        )

        ogg_path = await convert_to_ogg(wav_path)

        logger.info(
            "GeminiTTS: chunk=%s/%s успішно згенеровано",
            chunk_index,
            chunks_count,
        )

        return ogg_path

    finally:
        safe_remove_file(wav_path)
