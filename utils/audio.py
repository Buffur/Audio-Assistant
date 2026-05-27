# Файл: utils/audio.py

import asyncio
import logging
import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path

from config import EXPORT_AUDIO_CONCAT_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

FFMPEG_TIMEOUT_SECONDS = 90
FFMPEG_CONCAT_TIMEOUT_SECONDS = EXPORT_AUDIO_CONCAT_TIMEOUT_SECONDS
FFMPEG_MIN_CROSSFADE_SECONDS = 0.02


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


def _format_concat_file_path(file_path: str) -> str:
    path = Path(file_path).resolve().as_posix()
    return path.replace("'", "'\\''")


def _create_concat_list_file(audio_files: list[str]) -> str:
    list_file = create_temp_file_path(".txt")

    with open(list_file, "w", encoding="utf-8") as file:
        for audio_file in audio_files:
            file.write(f"file '{_format_concat_file_path(audio_file)}'\n")

    return list_file


async def _run_ffmpeg_concat(
    *,
    concat_list_file: str,
    output_file: str,
    stream_copy: bool,
) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_list_file,
    ]

    if stream_copy:
        command.extend(["-c", "copy", output_file])
    else:
        command.extend([
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
        ])

    process = None

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=FFMPEG_CONCAT_TIMEOUT_SECONDS,
        )

    except asyncio.TimeoutError:
        if process is not None:
            process.kill()
            await process.communicate()

        raise RuntimeError(
            "FFMPEG concat timeout: audio merge took longer than "
            f"{FFMPEG_CONCAT_TIMEOUT_SECONDS} seconds."
        )

    if process.returncode != 0:
        error_text = stderr.decode("utf-8", errors="ignore").strip()
        error_text = error_text[-1500:] if error_text else "Unknown ffmpeg concat error."

        raise RuntimeError(f"FFMPEG concat failed: {error_text}")


def _crossfade_seconds(crossfade_ms: int) -> float:
    return max(crossfade_ms / 1000, FFMPEG_MIN_CROSSFADE_SECONDS)


def _build_smooth_concat_filter(
    files_count: int,
    crossfade_ms: int,
) -> tuple[str, str]:
    crossfade = _crossfade_seconds(crossfade_ms)
    filters: list[str] = []

    for index in range(files_count):
        filters.append(
            f"[{index}:a]"
            "aresample=48000,"
            "aformat=sample_rates=48000:channel_layouts=mono,"
            "loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"asetpts=N/SR/TB[a{index}]"
        )

    current_label = "a0"

    for index in range(1, files_count):
        next_label = f"xf{index}"
        filters.append(
            f"[{current_label}][a{index}]"
            f"acrossfade=d={crossfade:.3f}:c1=tri:c2=tri"
            f"[{next_label}]"
        )
        current_label = next_label

    filters.append(
        f"[{current_label}]"
        "aresample=48000,"
        "aformat=sample_rates=48000:channel_layouts=mono[out]"
    )

    return ";".join(filters), "[out]"


async def _run_ffmpeg_smooth_concat(
    *,
    audio_files: list[str],
    output_file: str,
    crossfade_ms: int,
) -> None:
    filter_graph, output_label = _build_smooth_concat_filter(
        len(audio_files),
        crossfade_ms,
    )
    filter_script_file = create_temp_file_path(".ffgraph")

    with open(filter_script_file, "w", encoding="utf-8") as file:
        file.write(filter_graph)

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
    ]

    for audio_file in audio_files:
        command.extend(["-i", audio_file])

    command.extend([
        "-filter_complex_script",
        filter_script_file,
        "-map",
        output_label,
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
    ])

    process = None

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=FFMPEG_CONCAT_TIMEOUT_SECONDS,
        )

    except asyncio.TimeoutError:
        if process is not None:
            process.kill()
            await process.communicate()

        raise RuntimeError(
            "FFMPEG smooth concat timeout: audio merge took longer than "
            f"{FFMPEG_CONCAT_TIMEOUT_SECONDS} seconds."
        )

    finally:
        safe_remove_file(filter_script_file)

    if process.returncode != 0:
        error_text = stderr.decode("utf-8", errors="ignore").strip()
        error_text = error_text[-1500:] if error_text else "Unknown ffmpeg smooth concat error."

        raise RuntimeError(f"FFMPEG smooth concat failed: {error_text}")


async def concat_ogg_files(
    audio_files: list[str],
    *,
    smooth: bool = False,
    crossfade_ms: int = 120,
) -> str:
    """
    Merges OGG/Opus files into one Telegram-compatible OGG/Opus voice file.
    """
    audio_files = [file_path for file_path in audio_files if file_path]

    if not audio_files:
        raise ValueError("No audio files provided for concat.")

    for audio_file in audio_files:
        if not os.path.exists(audio_file):
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

    if not is_ffmpeg_available():
        raise RuntimeError(
            "ffmpeg not found. Check Dockerfile or system ffmpeg installation."
        )

    output_file = create_temp_file_path(".ogg")

    if len(audio_files) == 1:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(shutil.copyfile, audio_files[0], output_file),
                timeout=FFMPEG_CONCAT_TIMEOUT_SECONDS,
            )
            return output_file
        except asyncio.TimeoutError as error:
            safe_remove_file(output_file)
            raise RuntimeError(
                "FFMPEG concat timeout: single audio copy took longer than "
                f"{FFMPEG_CONCAT_TIMEOUT_SECONDS} seconds."
            ) from error
        except Exception:
            safe_remove_file(output_file)
            raise

    if smooth:
        try:
            await _run_ffmpeg_smooth_concat(
                audio_files=audio_files,
                output_file=output_file,
                crossfade_ms=crossfade_ms,
            )

            if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                raise RuntimeError("FFMPEG did not create a valid smooth OGG file.")

            logger.info(
                "FFMPEG: smooth audio concat completed, files=%s, output_size=%s bytes",
                len(audio_files),
                os.path.getsize(output_file),
            )

            return output_file

        except Exception:
            safe_remove_file(output_file)
            output_file = create_temp_file_path(".ogg")

            logger.warning(
                "FFMPEG: smooth concat failed, falling back to plain concat.",
                exc_info=True,
            )

    concat_list_file = _create_concat_list_file(audio_files)

    try:
        try:
            await _run_ffmpeg_concat(
                concat_list_file=concat_list_file,
                output_file=output_file,
                stream_copy=True,
            )
        except RuntimeError:
            safe_remove_file(output_file)
            output_file = create_temp_file_path(".ogg")

            logger.warning(
                "FFMPEG: stream-copy concat failed, retrying with re-encode.",
                exc_info=True,
            )

            await _run_ffmpeg_concat(
                concat_list_file=concat_list_file,
                output_file=output_file,
                stream_copy=False,
            )

        if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
            raise RuntimeError("FFMPEG did not create a valid merged OGG file.")

        logger.info(
            "FFMPEG: audio concat completed, files=%s, output_size=%s bytes",
            len(audio_files),
            os.path.getsize(output_file),
        )

        return output_file

    except Exception:
        safe_remove_file(output_file)
        raise

    finally:
        safe_remove_file(concat_list_file)


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
