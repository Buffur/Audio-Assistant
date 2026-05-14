# Файл: services/piper_tts.py

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from contextlib import suppress

from config import (
    BASE_DIR,
    PIPER_CONFIG_PATH,
    PIPER_EXECUTABLE,
    PIPER_LANGUAGE_MODELS_JSON,
    PIPER_LENGTH_SCALE,
    PIPER_MODEL_PATH,
    PIPER_MODELS_DIR,
    PIPER_SPEAKER,
    PIPER_TIMEOUT_SECONDS,
)
from utils.audio import convert_to_ogg, create_temp_file_path, safe_remove_file

logger = logging.getLogger(__name__)

DEFAULT_PIPER_LANGUAGE_MODELS = {
    "uk": {
        "female": {
            "model_path": "uk_UA-ukrainian_tts-medium.onnx",
            "config_path": "uk_UA-ukrainian_tts-medium.onnx.json",
            "speaker": 2,
        },
        "male": {
            "model_path": "uk_UA-ukrainian_tts-medium.onnx",
            "config_path": "uk_UA-ukrainian_tts-medium.onnx.json",
            "speaker": 1,
        },
    },
    "en": {
        "female": {
            "model_path": "en_US-amy-medium.onnx",
            "config_path": "en_US-amy-medium.onnx.json",
        },
        "male": {
            "model_path": "en_US-ryan-medium.onnx",
            "config_path": "en_US-ryan-medium.onnx.json",
        },
    },
    "de": {
        "female": {
            "model_path": "de_DE-eva_k-x_low.onnx",
            "config_path": "de_DE-eva_k-x_low.onnx.json",
        },
        "male": {
            "model_path": "de_DE-thorsten-medium.onnx",
            "config_path": "de_DE-thorsten-medium.onnx.json",
        },
    },
    "pl": {
        "female": {
            "model_path": "pl_PL-gosia-medium.onnx",
            "config_path": "pl_PL-gosia-medium.onnx.json",
        },
        "male": {
            "model_path": "pl_PL-darkman-medium.onnx",
            "config_path": "pl_PL-darkman-medium.onnx.json",
        },
    },
    "sk": {
        "female": {
            "model_path": "sk_SK-lili-medium.onnx",
            "config_path": "sk_SK-lili-medium.onnx.json",
        },
    },
    "cs": {
        "male": {
            "model_path": "cs_CZ-jirka-medium.onnx",
            "config_path": "cs_CZ-jirka-medium.onnx.json",
        },
    },
}

PIPER_MALE_VOICE_MARKERS = {
    "antonin",
    "conrad",
    "guy",
    "killian",
    "lukas",
    "marek",
    "ostap",
}


@dataclass(frozen=True)
class PiperVoiceSettings:
    language: str
    model_path: str
    config_path: str
    speaker: int | None
    length_scale: float


PIPER_LATIN_REPLACEMENTS = str.maketrans(
    {
        "a": "а",
        "b": "б",
        "c": "к",
        "d": "д",
        "e": "е",
        "f": "ф",
        "g": "ґ",
        "h": "х",
        "i": "і",
        "j": "дж",
        "k": "к",
        "l": "л",
        "m": "м",
        "n": "н",
        "o": "о",
        "p": "п",
        "q": "к",
        "r": "р",
        "s": "с",
        "t": "т",
        "u": "у",
        "v": "в",
        "w": "в",
        "x": "кс",
        "y": "і",
        "z": "з",
    }
)

PIPER_DIGIT_REPLACEMENTS = {
    "0": " нуль ",
    "1": " один ",
    "2": " два ",
    "3": " три ",
    "4": " чотири ",
    "5": " п'ять ",
    "6": " шість ",
    "7": " сім ",
    "8": " вісім ",
    "9": " дев'ять ",
}


def _rate_length_scale(rate: str) -> float:
    if rate == "-25%":
        return 1.25

    if rate == "+25%":
        return 0.85

    if rate == "+50%":
        return 0.70

    return 1.0


def _format_float(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _voice_language(voice: str) -> str:
    if not voice or "-" not in voice:
        return "uk"

    return voice.split("-", 1)[0].lower()


def _voice_gender(voice: str) -> str:
    voice_lower = (voice or "").lower()

    if any(marker in voice_lower for marker in PIPER_MALE_VOICE_MARKERS):
        return "male"

    return "female"


def _merge_language_models(
    base_models: dict[str, dict],
    overrides: dict[str, dict],
) -> dict[str, dict]:
    merged_models = {
        language: dict(model_config)
        for language, model_config in base_models.items()
    }

    for language, override_config in overrides.items():
        current_config = dict(merged_models.get(language, {}))

        for key, value in override_config.items():
            if (
                isinstance(value, dict)
                and isinstance(current_config.get(key), dict)
            ):
                current_config[key] = {
                    **current_config[key],
                    **value,
                }
            else:
                current_config[key] = value

        merged_models[language] = current_config

    return merged_models


def _resolve_piper_path(path: str) -> str:
    if not path:
        return ""

    path_obj = Path(path)

    if path_obj.is_absolute() and path_obj.exists():
        return str(path_obj)

    if path_obj.exists():
        return str(path_obj)

    models_dir_path = Path(PIPER_MODELS_DIR) / path_obj.name
    if models_dir_path.exists():
        return str(models_dir_path)

    local_models_path = BASE_DIR / "data" / "piper" / path_obj.name
    if local_models_path.exists():
        return str(local_models_path)

    if path_obj.is_absolute():
        return str(path_obj)

    return str(Path(PIPER_MODELS_DIR) / path_obj)


def _resolve_piper_executable() -> str | None:
    executable_path = Path(PIPER_EXECUTABLE)

    if executable_path.exists():
        return str(executable_path)

    found_executable = shutil.which(PIPER_EXECUTABLE)

    if found_executable:
        return found_executable

    python_dir = Path(sys.executable).parent

    for executable_name in ("piper.exe", "piper"):
        sibling_executable = python_dir / executable_name

        if sibling_executable.exists():
            return str(sibling_executable)

    return None


def _load_language_model_overrides() -> dict[str, dict]:
    if not PIPER_LANGUAGE_MODELS_JSON.strip():
        return {}

    try:
        parsed_value = json.loads(PIPER_LANGUAGE_MODELS_JSON)
    except json.JSONDecodeError:
        logger.exception("PiperTTS: некоректний PIPER_LANGUAGE_MODELS_JSON")
        return {}

    if not isinstance(parsed_value, dict):
        logger.warning("PiperTTS: PIPER_LANGUAGE_MODELS_JSON має бути JSON object")
        return {}

    overrides: dict[str, dict] = {}

    for language, settings in parsed_value.items():
        if isinstance(language, str) and isinstance(settings, dict):
            overrides[language.lower()] = settings

    return overrides


def get_piper_voice_settings(edge_voice: str) -> PiperVoiceSettings:
    language = _voice_language(edge_voice)
    gender = _voice_gender(edge_voice)
    language_models = _merge_language_models(
        DEFAULT_PIPER_LANGUAGE_MODELS,
        _load_language_model_overrides(),
    )
    language_config = dict(language_models.get(language) or {})

    if "model_path" in language_config:
        model_config = language_config
    else:
        model_config = dict(language_config.get(gender) or {})

    if language == "uk" and PIPER_MODEL_PATH.strip():
        override_model_path = _resolve_piper_path(PIPER_MODEL_PATH)
        default_model_path = _resolve_piper_path(str(model_config.get("model_path", "")))

        if Path(override_model_path).exists() or not Path(default_model_path).exists():
            model_config["model_path"] = PIPER_MODEL_PATH
            model_config["config_path"] = PIPER_CONFIG_PATH

    model_path = _resolve_piper_path(str(model_config.get("model_path", "")))
    config_path = _resolve_piper_path(str(model_config.get("config_path", "")))

    speaker = model_config.get("speaker", PIPER_SPEAKER)
    if speaker is not None:
        speaker = int(speaker)

    length_scale = float(model_config.get("length_scale", PIPER_LENGTH_SCALE))

    return PiperVoiceSettings(
        language=language,
        model_path=model_path,
        config_path=config_path,
        speaker=speaker,
        length_scale=length_scale,
    )


def is_piper_voice_configured(edge_voice: str) -> bool:
    settings = get_piper_voice_settings(edge_voice)
    return _is_piper_configured(settings)


def get_piper_cache_voice_name(edge_voice: str) -> str:
    settings = get_piper_voice_settings(edge_voice)

    return (
        f"piper:{settings.language}:"
        f"{_voice_gender(edge_voice)}:"
        f"{settings.model_path}:"
        f"{settings.config_path}:"
        f"{settings.speaker}:"
        f"{settings.length_scale}:"
        f"{edge_voice}"
    )


def _normalize_text_for_piper(text: str, language: str = "uk") -> str:
    normalized_text = unicodedata.normalize("NFC", text).casefold()

    if language == "uk":
        normalized_text = normalized_text.translate(PIPER_LATIN_REPLACEMENTS)

        for digit, replacement in PIPER_DIGIT_REPLACEMENTS.items():
            normalized_text = normalized_text.replace(digit, replacement)

        normalized_text = re.sub(r"[()\[\]{}<>]", " ", normalized_text)

    normalized_text = re.sub(r"\s+", " ", normalized_text)

    return normalized_text.strip()


def _is_piper_configured(settings: PiperVoiceSettings) -> bool:
    if not settings.model_path.strip():
        return False

    if not Path(settings.model_path).exists():
        return False

    if settings.config_path.strip() and not Path(settings.config_path).exists():
        return False

    return _resolve_piper_executable() is not None


def _build_piper_command(
    *,
    settings: PiperVoiceSettings,
    input_path: str,
    wav_path: str,
    rate: str,
) -> list[str]:
    length_scale = settings.length_scale * _rate_length_scale(rate)

    command = [
        _resolve_piper_executable() or PIPER_EXECUTABLE,
        "--model",
        settings.model_path,
        "--input_file",
        input_path,
        "--output_file",
        wav_path,
    ]

    if settings.config_path.strip():
        command.extend(["--config", settings.config_path])

    if settings.speaker is not None:
        command.extend(["--speaker", str(settings.speaker)])

    if length_scale != 1.0:
        command.extend(["--length_scale", _format_float(length_scale)])

    return command


def _ensure_piper_configured(settings: PiperVoiceSettings) -> None:
    if not settings.model_path.strip():
        raise RuntimeError(
            f"Piper model path is not configured for language: {settings.language}"
        )

    if not Path(settings.model_path).exists():
        raise RuntimeError(f"Piper model file not found: {settings.model_path}")

    if settings.config_path.strip() and not Path(settings.config_path).exists():
        raise RuntimeError(f"Piper config file not found: {settings.config_path}")

    if _resolve_piper_executable() is None:
        raise RuntimeError(f"Piper executable not found: {PIPER_EXECUTABLE}")


async def generate_piper_tts_ogg(
    *,
    text: str,
    voice: str,
    rate: str,
    chunk_index: int,
    chunks_count: int,
) -> str:
    """
    Генерує OGG/Opus voice-файл через локальний Piper CLI.

    Piper повертає WAV, після чого ми конвертуємо його в OGG/Opus
    для Telegram voice.
    """
    settings = get_piper_voice_settings(voice)
    _ensure_piper_configured(settings)

    input_path = create_temp_file_path(".txt")
    wav_path = create_temp_file_path(".wav")
    command = _build_piper_command(
        settings=settings,
        input_path=input_path,
        wav_path=wav_path,
        rate=rate,
    )
    process = None

    try:
        piper_text = _normalize_text_for_piper(text, settings.language)

        with open(input_path, "w", encoding="utf-8", newline="\n") as input_file:
            input_file.write(piper_text)
            input_file.write("\n")

        logger.info(
            "PiperTTS: генерація chunk=%s/%s, model=%s, text_length=%s",
            chunk_index,
            chunks_count,
            settings.model_path,
            len(piper_text),
        )

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=PIPER_TIMEOUT_SECONDS,
        )

        if process.returncode != 0:
            error_text = stderr.decode("utf-8", errors="ignore").strip()
            output_text = stdout.decode("utf-8", errors="ignore").strip()
            details = error_text or output_text or "Unknown Piper error."
            raise RuntimeError(f"Piper failed: {details[-1500:]}")

        if not os.path.exists(wav_path) or os.path.getsize(wav_path) == 0:
            raise RuntimeError("Piper не створив коректний WAV-файл.")

        ogg_path = await convert_to_ogg(wav_path)

        logger.info(
            "PiperTTS: chunk=%s/%s успішно згенеровано",
            chunk_index,
            chunks_count,
        )

        return ogg_path

    except asyncio.TimeoutError as error:
        if process is not None:
            with suppress(Exception):
                process.kill()
                await process.communicate()

        raise RuntimeError(
            f"Piper timeout: генерація тривала довше {PIPER_TIMEOUT_SECONDS} секунд."
        ) from error

    finally:
        safe_remove_file(input_path)
        safe_remove_file(wav_path)
