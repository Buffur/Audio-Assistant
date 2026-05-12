# Файл: utils/audio.py

import asyncio
import logging
import os
import shutil
import tempfile
from contextlib import suppress

logger = logging.getLogger(__name__)

FFMPEG_TIMEOUT_SECONDS = 90


def is_ffmpeg_available() -> bool:
    """
    Перевіряє, чи доступний ffmpeg у системі / Docker-контейнері.
    """
    return shutil.which("ffmpeg") is not None


def safe_remove_file(path: str | None) -> None:
    """
    Безпечно видаляє файл.

    Використовується для тимчасових mp3/ogg файлів,
    щоб не засмічувати контейнер.
    """
    if not path:
        return

    with suppress(Exception):
        if os.path.exists(path):
            os.remove(path)


def create_temp_file_path(suffix: str) -> str:
    """
    Створює шлях до тимчасового файлу і одразу закриває дескриптор.

    Це безпечніше, ніж робити input_file.replace(".mp3", ".ogg"),
    бо ми точно отримуємо унікальний шлях.
    """
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.close()
    return temp_file.name


async def convert_to_ogg(input_file: str) -> str:
    """
    Конвертує аудіофайл у OGG/Opus для Telegram voice.

    Повертає шлях до .ogg файлу.
    Якщо конвертація не вдалася — кидає RuntimeError.
    """
    if not input_file or not os.path.exists(input_file):
        raise FileNotFoundError(f"Вхідний аудіофайл не знайдено: {input_file}")

    if not is_ffmpeg_available():
        raise RuntimeError(
            "ffmpeg не знайдено. Перевір Dockerfile або встановлення ffmpeg у системі."
        )

    output_file = create_temp_file_path(".ogg")

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_file,
        "-vn",
        "-c:a",
        "libopus",
        "-b:a",
        "64k",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-f",
        "ogg",
        output_file,
    ]

    logger.info("FFMPEG: старт конвертації mp3 -> ogg")

    process = None

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )

    except asyncio.TimeoutError:
        if process is not None:
            process.kill()
            await process.communicate()

        safe_remove_file(output_file)

        raise RuntimeError(
            f"FFMPEG timeout: конвертація тривала довше {FFMPEG_TIMEOUT_SECONDS} секунд."
        )

    except Exception:
        safe_remove_file(output_file)
        logger.exception("FFMPEG: помилка запуску процесу")
        raise

    if process.returncode != 0:
        safe_remove_file(output_file)

        error_text = stderr.decode("utf-8", errors="ignore").strip()
        error_text = error_text[-1500:] if error_text else "Невідома помилка ffmpeg."

        logger.error("FFMPEG ERROR: %s", error_text)

        raise RuntimeError(f"FFMPEG failed: {error_text}")

    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        safe_remove_file(output_file)
        raise RuntimeError("FFMPEG не створив коректний OGG-файл.")

    logger.info(
        "FFMPEG: конвертацію завершено, output_size=%s bytes",
        os.path.getsize(output_file)
    )

    return output_file