# Файл: services/reading_service.py

import asyncio
import json
import logging
import os
import time
from contextlib import suppress
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

from aiogram import Bot
from aiogram.types import Message
from redis.exceptions import RedisError

from config import (
    BOT_TOKEN,
    EXPORT_AUDIO_CROSSFADE_MS,
    EXPORT_AUDIO_MAX_SIZE_MB,
    EXPORT_AUDIO_SMOOTH_MERGE_ENABLED,
    READING_AUDIO_QUEUE_BACKEND,
    READING_AUDIO_QUEUE_MAX_SIZE,
    READING_AUDIO_QUEUE_REDIS_KEY,
)
from keyboards.reading import reading_navigation_keyboard
from services.reading_session_store import (
    cleanup_reading_session,
    get_reading_session,
    update_reading_session,
)
from services.redis_client import get_redis_client
from services.tts import generate_voice
from services.usage_limits_service import is_premium_user
from services.user_settings_service import (
    build_user_tts_provider_chain,
    get_effective_user_settings,
    get_effective_user_tts_provider,
)
from services.voice_selector import select_voice_for_text
from services.voice_sender import safe_remove_file, send_voice_files
from texts.messages import (
    ALL_PARTS_SENT_AFTER_SUMMARY_TEXT,
    ALL_PARTS_SENT_TEXT,
    AUDIO_QUEUE_FULL_TEXT,
    BACKGROUND_GENERATION_ERROR,
    CHUNK_AUDIO_GENERATION_ERROR,
    EXPORT_AUDIO_CAPTION_TEXT,
    EXPORT_AUDIO_CONCATENATING_TEXT,
    EXPORT_AUDIO_GENERATION_ERROR,
    SESSION_NOT_FOUND_OR_FINISHED_TEXT,
    build_audio_generation_queued_text,
    build_export_audio_part_text,
    build_export_audio_progress_text,
    build_export_audio_queued_text,
    build_export_audio_too_large_text,
    build_generating_audio_progress_text,
    build_generating_chunk_text,
    build_loading_chunk_text,
    build_part_audio_caption,
    build_part_caption,
)
from utils.audio import concat_ogg_files

logger = logging.getLogger(__name__)

READING_AUDIO_QUEUE_FLUSH_TIMEOUT_SECONDS = 10.0
REDIS_AUDIO_QUEUE_BLPOP_TIMEOUT_SECONDS = 5
REDIS_PREFETCH_WAIT_SECONDS = 3.0

AudioGenerationJob = Callable[[], Awaitable[None]]
SerializedAudioJob = dict[str, object]

_audio_generation_queue: asyncio.Queue[AudioGenerationJob] | None = None
_audio_generation_worker_task: asyncio.Task | None = None
_redis_audio_generation_worker_task: asyncio.Task | None = None


class _TelegramMessageProxy:
    """
    Мінімальний Message-like adapter для Redis worker jobs.

    Він реалізує тільки методи, які потрібні reading_service/voice_sender:
    answer(...) і answer_voice(...).
    """

    def __init__(self, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat = SimpleNamespace(id=chat_id)

    async def answer(self, text: str, **kwargs):
        return await self.bot.send_message(
            chat_id=self.chat.id,
            text=text,
            **kwargs,
        )

    async def answer_voice(self, voice, caption=None, reply_markup=None):
        return await self.bot.send_voice(
            chat_id=self.chat.id,
            voice=voice,
            caption=caption,
            reply_markup=reply_markup,
        )


class _TelegramStatusMessageProxy:
    def __init__(self, bot: Bot, chat_id: int, message_id: int) -> None:
        self.bot = bot
        self.chat = SimpleNamespace(id=chat_id)
        self.message_id = message_id

    async def edit_text(self, text: str) -> None:
        await self.bot.edit_message_text(
            chat_id=self.chat.id,
            message_id=self.message_id,
            text=text,
        )

    async def delete(self) -> None:
        await self.bot.delete_message(
            chat_id=self.chat.id,
            message_id=self.message_id,
        )


async def _audio_generation_worker(
    queue: asyncio.Queue[AudioGenerationJob],
) -> None:
    while True:
        job = await queue.get()

        try:
            await job()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ReadingService: background audio generation job failed")
        finally:
            queue.task_done()


def _use_redis_audio_queue() -> bool:
    return READING_AUDIO_QUEUE_BACKEND == "redis"


def _message_chat_id(message: Message) -> int | None:
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)

    if isinstance(chat_id, int):
        return chat_id

    return None


def _status_message_id(message: Message | None) -> int | None:
    message_id = getattr(message, "message_id", None)

    if isinstance(message_id, int):
        return message_id

    return None


def _serialize_audio_job(job: SerializedAudioJob) -> str:
    payload = dict(job)
    payload.setdefault("created_at", time.time())
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


async def _run_prefetch_audio_job(job: SerializedAudioJob) -> None:
    user_id = int(job["user_id"])
    expected_session_id = str(job["session_id"])
    chunk_index = int(job["chunk_index"])
    chunk_text = str(job["chunk_text"])
    voice = str(job["voice"])
    rate = str(job["rate"])
    provider_chain = [
        str(provider)
        for provider in job.get("provider_chain", [])
        if str(provider).strip()
    ]

    session = await get_reading_session(user_id)

    if not _is_same_session(session, expected_session_id):
        return

    await update_reading_session(
        user_id,
        prefetch_state="running",
        prefetch_index=chunk_index,
        prefetch_error="",
    )

    audio_files: list[str] = []

    try:
        audio_files = await generate_voice(
            text=chunk_text,
            voice=voice,
            rate=rate,
            provider_chain=provider_chain,
        )

        session = await get_reading_session(user_id)

        if not _is_same_session(session, expected_session_id):
            _cleanup_audio_files(audio_files)
            return

        await update_reading_session(
            user_id,
            prefetch_state="ready",
            prefetch_index=chunk_index,
            prefetch_audio_files=audio_files,
            prefetch_error="",
        )
        audio_files = []

    except Exception as error:
        logger.exception(
            "ReadingService: Redis prefetch job failed user_id=%s chunk_index=%s",
            user_id,
            chunk_index,
        )
        await update_reading_session(
            user_id,
            prefetch_state="failed",
            prefetch_index=chunk_index,
            prefetch_audio_files=[],
            prefetch_error=str(error),
        )

    finally:
        _cleanup_audio_files(audio_files)


async def _run_serialized_audio_job(bot: Bot, job: SerializedAudioJob) -> None:
    job_type = str(job.get("type") or "")

    if job_type == "prefetch_chunk":
        await _run_prefetch_audio_job(job)
        return

    user_id = int(job["user_id"])
    chat_id = int(job["chat_id"])
    expected_session_id = str(job["session_id"])
    status_message_id = job.get("status_message_id")

    message = _TelegramMessageProxy(bot, chat_id)
    status_msg = (
        _TelegramStatusMessageProxy(bot, chat_id, int(status_message_id))
        if isinstance(status_message_id, int)
        else None
    )

    if job_type == "send_chunk":
        await _send_audio_chunk_now(
            message=message,  # type: ignore[arg-type]
            user_id=user_id,
            expected_session_id=expected_session_id,
            status_msg=status_msg,  # type: ignore[arg-type]
        )
        return

    if job_type == "export_audio":
        await _export_reading_audio_now(
            message=message,  # type: ignore[arg-type]
            user_id=user_id,
            expected_session_id=expected_session_id,
            status_msg=status_msg,  # type: ignore[arg-type]
        )
        return

    logger.warning("ReadingService: unknown Redis audio job type=%s", job_type)


async def _redis_audio_generation_worker() -> None:
    bot = Bot(BOT_TOKEN)

    try:
        while True:
            try:
                client = await get_redis_client()
                result = await client.blpop(
                    READING_AUDIO_QUEUE_REDIS_KEY,
                    timeout=REDIS_AUDIO_QUEUE_BLPOP_TIMEOUT_SECONDS,
                )

                if result is None:
                    continue

                _queue_key, raw_job = result
                job = json.loads(raw_job)

                if not isinstance(job, dict):
                    logger.warning("ReadingService: Redis job is not an object")
                    continue

                await _run_serialized_audio_job(bot, job)

            except asyncio.CancelledError:
                raise

            except (RedisError, json.JSONDecodeError, KeyError, ValueError):
                logger.exception("ReadingService: Redis audio worker job failed")
                await asyncio.sleep(1)

            except Exception:
                logger.exception("ReadingService: Redis audio generation job failed")

    finally:
        await bot.session.close()


def _ensure_redis_audio_generation_worker() -> None:
    global _redis_audio_generation_worker_task

    if (
        _redis_audio_generation_worker_task is None
        or _redis_audio_generation_worker_task.done()
    ):
        _redis_audio_generation_worker_task = asyncio.create_task(
            _redis_audio_generation_worker()
        )


async def _redis_audio_queue_position() -> int:
    client = await get_redis_client()
    queue_size = await client.llen(READING_AUDIO_QUEUE_REDIS_KEY)
    return int(queue_size) + 1


async def _enqueue_redis_audio_job(job: SerializedAudioJob) -> None:
    _ensure_redis_audio_generation_worker()
    client = await get_redis_client()

    queue_size = await client.llen(READING_AUDIO_QUEUE_REDIS_KEY)

    if int(queue_size) >= READING_AUDIO_QUEUE_MAX_SIZE:
        raise asyncio.QueueFull

    await client.rpush(READING_AUDIO_QUEUE_REDIS_KEY, _serialize_audio_job(job))


def _ensure_audio_generation_queue() -> asyncio.Queue[AudioGenerationJob]:
    global _audio_generation_queue
    global _audio_generation_worker_task

    if _audio_generation_queue is None:
        _audio_generation_queue = asyncio.Queue(
            maxsize=READING_AUDIO_QUEUE_MAX_SIZE,
        )

    if (
        _audio_generation_worker_task is None
        or _audio_generation_worker_task.done()
    ):
        _audio_generation_worker_task = asyncio.create_task(
            _audio_generation_worker(_audio_generation_queue)
        )

    return _audio_generation_queue


async def close_reading_audio_queue(
    timeout_seconds: float = READING_AUDIO_QUEUE_FLUSH_TIMEOUT_SECONDS,
) -> None:
    global _audio_generation_queue
    global _audio_generation_worker_task
    global _redis_audio_generation_worker_task

    queue = _audio_generation_queue
    worker_task = _audio_generation_worker_task
    redis_worker_task = _redis_audio_generation_worker_task

    if queue is not None:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(queue.join(), timeout=timeout_seconds)

    if worker_task is not None and not worker_task.done():
        worker_task.cancel()

        with suppress(asyncio.CancelledError):
            await worker_task

    _audio_generation_queue = None
    _audio_generation_worker_task = None

    if redis_worker_task is not None and not redis_worker_task.done():
        redis_worker_task.cancel()

        with suppress(asyncio.CancelledError):
            await redis_worker_task

    _redis_audio_generation_worker_task = None


async def safe_delete_message(message: Message | None) -> None:
    """
    Безпечно видаляє повідомлення.
    Якщо Telegram не дозволив видалення — просто ігноруємо.
    """
    if message is None:
        return

    with suppress(Exception):
        await message.delete()


async def safe_edit_message(message: Message | None, text: str) -> None:
    if message is None:
        return

    with suppress(Exception):
        await message.edit_text(text)


def _is_same_session(session: dict | None, session_id: str | None) -> bool:
    if not session:
        return False

    if session_id is None:
        return True

    return session.get("session_id") == session_id


async def _finish_generation_if_session(
    user_id: int,
    session_id: str | None,
) -> None:
    session = await get_reading_session(user_id)

    if _is_same_session(session, session_id):
        await update_reading_session(user_id, is_generating=False)


def _export_max_size_bytes() -> int:
    return EXPORT_AUDIO_MAX_SIZE_MB * 1024 * 1024


def _file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 * 1024)


def _cleanup_audio_files(audio_files: list[str]) -> None:
    for audio_path in audio_files:
        safe_remove_file(audio_path)


async def cleanup_session(user_id: int) -> None:
    """
    Public wrapper для handlers.
    """
    await cleanup_reading_session(user_id)


async def _send_audio_files(
    message: Message,
    audio_files: list[str],
    caption: str | None = None,
    reply_markup=None,
    caption_builder=None,
) -> None:
    """
    Надсилає audio-файли як voice і завжди видаляє тимчасові файли.
    """
    await send_voice_files(
        message=message,
        audio_files=audio_files,
        caption=caption,
        reply_markup=reply_markup,
        caption_builder=caption_builder,
    )


async def _export_reading_audio_now(
    message: Message,
    user_id: int,
    expected_session_id: str | None,
    status_msg: Message | None,
) -> None:
    session = await get_reading_session(user_id)

    if not _is_same_session(session, expected_session_id):
        await safe_delete_message(status_msg)
        return

    chunks = session.get("chunks") or []

    if not chunks:
        await safe_delete_message(status_msg)
        await message.answer(SESSION_NOT_FOUND_OR_FINISHED_TEXT)
        return

    generated_audio_files: list[str] = []
    combined_audio_file: str | None = None

    try:
        voice_pref, rate = await get_effective_user_settings(user_id)
        tts_provider = await get_effective_user_tts_provider(user_id)
        total_parts = len(chunks)

        for index, chunk_text in enumerate(chunks, start=1):
            current_session = await get_reading_session(user_id)

            if not _is_same_session(current_session, expected_session_id):
                await safe_delete_message(status_msg)
                return

            await safe_edit_message(
                status_msg,
                build_export_audio_part_text(index, total_parts),
            )

            voice = select_voice_for_text(chunk_text, voice_pref)
            provider_chain = build_user_tts_provider_chain(
                tts_provider,
                voice=voice,
            )

            async def progress_callback(
                completed_chunks: int,
                chunks_count: int,
                provider: str,
                cache_hit: bool,
            ) -> None:
                if chunks_count <= 1:
                    return

                await safe_edit_message(
                    status_msg,
                    build_export_audio_progress_text(
                        current_part=index,
                        total_parts=total_parts,
                        completed_audio_chunks=completed_chunks,
                        total_audio_chunks=chunks_count,
                        provider=provider,
                        cache_hit=cache_hit,
                    ),
                )

            audio_files = await generate_voice(
                text=chunk_text,
                voice=voice,
                rate=rate,
                provider_chain=provider_chain,
                progress_callback=progress_callback,
            )

            if not audio_files:
                raise RuntimeError(
                    f"TTS returned no audio files for export part {index}/{total_parts}"
                )

            generated_audio_files.extend(audio_files)

        await safe_edit_message(status_msg, EXPORT_AUDIO_CONCATENATING_TEXT)

        combined_audio_file = await concat_ogg_files(
            generated_audio_files,
            smooth=EXPORT_AUDIO_SMOOTH_MERGE_ENABLED,
            crossfade_ms=EXPORT_AUDIO_CROSSFADE_MS,
        )
        combined_file_size_mb = _file_size_mb(combined_audio_file)

        if os.path.getsize(combined_audio_file) > _export_max_size_bytes():
            await safe_delete_message(status_msg)
            await message.answer(
                build_export_audio_too_large_text(
                    file_size_mb=combined_file_size_mb,
                    max_size_mb=EXPORT_AUDIO_MAX_SIZE_MB,
                )
            )
            return

        current_session = await get_reading_session(user_id)

        if not _is_same_session(current_session, expected_session_id):
            await safe_delete_message(status_msg)
            return

        await safe_delete_message(status_msg)

        await _send_audio_files(
            message=message,
            audio_files=[combined_audio_file],
            caption=EXPORT_AUDIO_CAPTION_TEXT,
        )
        combined_audio_file = None

    except Exception:
        logger.exception(
            "ReadingService: full audio export failed user_id=%s",
            user_id,
        )
        await safe_delete_message(status_msg)
        await message.answer(EXPORT_AUDIO_GENERATION_ERROR)

    finally:
        _cleanup_audio_files(generated_audio_files)
        safe_remove_file(combined_audio_file)
        await _finish_generation_if_session(user_id, expected_session_id)


async def export_reading_audio(
    message: Message,
    user_id: int,
    expected_session_id: str | None = None,
) -> None:
    session = await get_reading_session(user_id)

    if not _is_same_session(session, expected_session_id):
        await message.answer(SESSION_NOT_FOUND_OR_FINISHED_TEXT)
        return

    chunks = session.get("chunks") or []
    session_id = session.get("session_id", "legacy")

    if not chunks:
        await cleanup_session(user_id)
        await message.answer(SESSION_NOT_FOUND_OR_FINISHED_TEXT)
        return

    await update_reading_session(user_id, is_generating=True)

    chat_id = _message_chat_id(message)

    if _use_redis_audio_queue() and chat_id is not None:
        status_msg = None

        try:
            queued_position = await _redis_audio_queue_position()
            status_msg = await message.answer(
                build_export_audio_queued_text(
                    total_parts=len(chunks),
                    queue_position=queued_position,
                )
            )
            await _enqueue_redis_audio_job(
                {
                    "type": "export_audio",
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "session_id": session_id,
                    "status_message_id": _status_message_id(status_msg),
                }
            )
            return

        except asyncio.QueueFull:
            await safe_delete_message(status_msg)
            await _finish_generation_if_session(user_id, session_id)
            await message.answer(AUDIO_QUEUE_FULL_TEXT)
            return

        except RedisError:
            logger.exception(
                "ReadingService: Redis export queue failed; falling back to "
                "memory queue user_id=%s",
                user_id,
            )
            await safe_delete_message(status_msg)

    queue = _ensure_audio_generation_queue()
    queued_position = queue.qsize() + 1
    status_msg = await message.answer(
        build_export_audio_queued_text(
            total_parts=len(chunks),
            queue_position=queued_position,
        )
    )

    async def job() -> None:
        await _export_reading_audio_now(
            message=message,
            user_id=user_id,
            expected_session_id=session_id,
            status_msg=status_msg,
        )

    try:
        queue.put_nowait(job)
    except asyncio.QueueFull:
        await safe_delete_message(status_msg)
        await _finish_generation_if_session(user_id, session_id)
        await message.answer(AUDIO_QUEUE_FULL_TEXT)


async def reply_with_voice(
    message: Message,
    user_id: int,
    text: str,
    status_msg: Message | None = None,
) -> None:
    """
    Надсилає службовий текст голосом.
    Якщо TTS не спрацював — надсилає звичайний текст.
    """
    await safe_delete_message(status_msg)

    clean_text = (
        text.replace("❌", "")
        .replace("✅", "")
        .replace("🛑", "")
        .replace("📚", "")
        .replace("⏳", "")
        .replace("📝", "")
        .strip()
    )

    if not clean_text:
        await message.answer(text)
        return

    try:
        voice_pref, rate = await get_effective_user_settings(user_id)
        tts_provider = await get_effective_user_tts_provider(user_id)
        voice = select_voice_for_text(clean_text, voice_pref)

        audio_files = await generate_voice(
            text=clean_text,
            voice=voice,
            rate=rate,
            provider_chain=build_user_tts_provider_chain(
                tts_provider,
                voice=voice,
            ),
        )

        if not audio_files:
            await message.answer(text)
            return

        await _send_audio_files(
            message=message,
            audio_files=audio_files,
            caption=text,
        )

    except Exception:
        logger.exception(
            "ReadingService: не вдалося озвучити службове повідомлення user_id=%s",
            user_id,
        )
        await message.answer(text)


async def _get_audio_from_prefetch_or_generate(
    *,
    message: Message,
    user_id: int,
    session: dict,
    chunk_text: str,
    voice: str,
    rate: str,
    provider_chain: list[str],
    current_part: int,
    total_parts: int,
    status_msg: Message | None = None,
) -> list[str]:
    """
    Бере аудіо з prefetch_task або генерує його вручну.
    """
    current_index = current_part - 1
    prefetch_state = str(session.get("prefetch_state") or "")
    prefetch_index = session.get("prefetch_index")

    if prefetch_index == current_index and prefetch_state in {"queued", "running"}:
        await safe_edit_message(
            status_msg,
            build_loading_chunk_text(current_part, total_parts),
        )
        deadline = time.monotonic() + REDIS_PREFETCH_WAIT_SECONDS

        while time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            refreshed_session = await get_reading_session(user_id)

            if not refreshed_session:
                break

            prefetch_state = str(refreshed_session.get("prefetch_state") or "")
            session = refreshed_session

            if prefetch_state not in {"queued", "running"}:
                break

    prefetch_audio_files = session.get("prefetch_audio_files") or []

    if (
        session.get("prefetch_index") == current_index
        and session.get("prefetch_state") == "ready"
        and isinstance(prefetch_audio_files, list)
        and prefetch_audio_files
    ):
        await update_reading_session(
            user_id,
            prefetch_state="none",
            prefetch_index=-1,
            prefetch_audio_files=[],
            prefetch_error="",
        )
        await safe_delete_message(status_msg)
        return [str(file_path) for file_path in prefetch_audio_files]

    if (
        session.get("prefetch_index") == current_index
        and session.get("prefetch_state") == "failed"
    ):
        await update_reading_session(
            user_id,
            prefetch_state="none",
            prefetch_index=-1,
            prefetch_audio_files=[],
            prefetch_error="",
        )

    prefetch_task = session.get("prefetch_task")
    if prefetch_task:
        if not prefetch_task.done():
            await safe_edit_message(
                status_msg,
                build_loading_chunk_text(current_part, total_parts),
            )

        try:
            audio_files = await prefetch_task

        except asyncio.CancelledError:
            logger.info(
                "ReadingService: prefetch_task скасовано, генерую вручну user_id=%s",
                user_id,
            )
            audio_files = await generate_voice(
                chunk_text,
                voice,
                rate,
                provider_chain=provider_chain,
            )

        except Exception:
            logger.exception(
                "ReadingService: помилка prefetch_task, генерую вручну user_id=%s",
                user_id,
            )
            audio_files = await generate_voice(
                chunk_text,
                voice,
                rate,
                provider_chain=provider_chain,
            )

        await update_reading_session(user_id, prefetch_task=None)
        await safe_delete_message(status_msg)
        return audio_files

    await safe_edit_message(
        status_msg,
        build_generating_chunk_text(current_part, total_parts),
    )

    async def progress_callback(
        completed_chunks: int,
        chunks_count: int,
        provider: str,
        cache_hit: bool,
    ) -> None:
        if chunks_count <= 1:
            return

        await safe_edit_message(
            status_msg,
            build_generating_audio_progress_text(
                current_part=current_part,
                total_parts=total_parts,
                completed_audio_chunks=completed_chunks,
                total_audio_chunks=chunks_count,
                provider=provider,
                cache_hit=cache_hit,
            ),
        )

    try:
        audio_files = await generate_voice(
            chunk_text,
            voice,
            rate,
            provider_chain=provider_chain,
            progress_callback=progress_callback,
        )
        return audio_files

    finally:
        await safe_delete_message(status_msg)


async def _start_prefetch_next_chunk(
    *,
    user_id: int,
    session_id: str,
    chunks: list[str],
    next_index: int,
    voice_pref: str,
    rate: str,
    tts_provider: str,
) -> None:
    """
    Запускає фонову генерацію наступної частини.
    """
    if next_index >= len(chunks):
        return

    next_chunk = chunks[next_index]
    next_voice = select_voice_for_text(next_chunk, voice_pref)
    provider_chain = build_user_tts_provider_chain(
        tts_provider,
        voice=next_voice,
    )

    if _use_redis_audio_queue():
        await update_reading_session(
            user_id,
            prefetch_state="queued",
            prefetch_index=next_index,
            prefetch_audio_files=[],
            prefetch_error="",
        )

        try:
            await _enqueue_redis_audio_job(
                {
                    "type": "prefetch_chunk",
                    "user_id": user_id,
                    "session_id": session_id,
                    "chunk_index": next_index,
                    "chunk_text": next_chunk,
                    "voice": next_voice,
                    "rate": rate,
                    "provider_chain": provider_chain,
                }
            )
            return
        except (RedisError, asyncio.QueueFull):
            logger.exception(
                "ReadingService: failed to enqueue Redis prefetch job user_id=%s",
                user_id,
            )
            await update_reading_session(
                user_id,
                prefetch_state="failed",
                prefetch_index=next_index,
                prefetch_audio_files=[],
                prefetch_error="queue_failed",
            )
            return

    prefetch_task = asyncio.create_task(
        generate_voice(
            text=next_chunk,
            voice=next_voice,
            rate=rate,
            provider_chain=provider_chain,
        )
    )

    await update_reading_session(
        user_id,
        prefetch_task=prefetch_task,
    )


async def _send_audio_chunk_now(
    message: Message,
    user_id: int,
    expected_session_id: str | None,
    status_msg: Message | None,
) -> None:
    """
    Надсилає поточну частину тексту голосом і запускає prefetch наступної.
    """
    session = await get_reading_session(user_id)

    if not _is_same_session(session, expected_session_id):
        await safe_delete_message(status_msg)
        return

    chunks = session.get("chunks") or []
    index = int(session.get("index", 0))
    current_session_id = session.get("session_id", "legacy")

    if not chunks:
        await cleanup_session(user_id)
        await message.answer("❌ У сесії немає тексту для читання.")
        return

    if index >= len(chunks):
        await cleanup_session(user_id)
        await message.answer("✅ Всі частини вже були надіслані.")
        return

    chunk_text = chunks[index]

    voice_pref, rate = await get_effective_user_settings(user_id)
    tts_provider = await get_effective_user_tts_provider(user_id)
    voice = select_voice_for_text(chunk_text, voice_pref)
    provider_chain = build_user_tts_provider_chain(tts_provider, voice=voice)

    try:
        audio_files = await _get_audio_from_prefetch_or_generate(
            message=message,
            user_id=user_id,
            session=session,
            chunk_text=chunk_text,
            voice=voice,
            rate=rate,
            provider_chain=provider_chain,
            current_part=index + 1,
            total_parts=len(chunks),
            status_msg=status_msg,
        )

        if not audio_files:
            logger.warning(
                "ReadingService: TTS повернув порожній список user_id=%s, index=%s",
                user_id,
                index,
            )
            await message.answer(CHUNK_AUDIO_GENERATION_ERROR)
            return

        current_session = await get_reading_session(user_id)

        if not _is_same_session(current_session, expected_session_id):
            for audio_path in audio_files:
                safe_remove_file(audio_path)
            return

        new_index = index + 1
        has_next = new_index < len(chunks)
        summary_already_generated = bool(current_session.get("summary_text"))

        await update_reading_session(
            user_id,
            index=new_index,
        )

        can_export_audio = (
            await is_premium_user(user_id)
            and (len(chunks) > 1 or len(audio_files) > 1)
        )
        keyboard = reading_navigation_keyboard(
            has_next=has_next,
            session_id=current_session_id,
            can_export_audio=can_export_audio,
            show_summary_button=not summary_already_generated,
        )
        part_caption = build_part_caption(index + 1, len(chunks))

        await _send_audio_files(
            message=message,
            audio_files=audio_files,
            caption=part_caption,
            reply_markup=keyboard,
            caption_builder=lambda audio_index, audio_count, _caption: (
                build_part_audio_caption(
                    current_part=index + 1,
                    total_parts=len(chunks),
                    current_audio=audio_index,
                    total_audio=audio_count,
                )
            ),
        )

        if not has_next:
            await message.answer(
                ALL_PARTS_SENT_AFTER_SUMMARY_TEXT
                if summary_already_generated
                else ALL_PARTS_SENT_TEXT
            )
            return

        await _start_prefetch_next_chunk(
            user_id=user_id,
            session_id=current_session_id,
            chunks=chunks,
            next_index=new_index,
            voice_pref=voice_pref,
            rate=rate,
            tts_provider=tts_provider,
        )

    except Exception:
        logger.exception(
            "ReadingService: помилка надсилання audio chunk user_id=%s, index=%s",
            user_id,
            index,
        )
        await message.answer(BACKGROUND_GENERATION_ERROR)

    finally:
        await _finish_generation_if_session(user_id, expected_session_id)


async def send_audio_chunk(message: Message, user_id: int) -> None:
    """
    Queues current reading chunk audio generation in the background.
    """
    session = await get_reading_session(user_id)

    if not session:
        await message.answer(SESSION_NOT_FOUND_OR_FINISHED_TEXT)
        return

    chunks = session.get("chunks") or []
    index = int(session.get("index", 0))
    session_id = session.get("session_id", "legacy")

    if not chunks:
        await cleanup_session(user_id)
        await message.answer("❌ У сесії немає тексту для читання.")
        return

    if index >= len(chunks):
        await cleanup_session(user_id)
        await message.answer("✅ Всі частини вже були надіслані.")
        return

    await update_reading_session(user_id, is_generating=True)

    chat_id = _message_chat_id(message)

    if _use_redis_audio_queue() and chat_id is not None:
        status_msg = None

        try:
            queued_position = await _redis_audio_queue_position()
            status_msg = await message.answer(
                build_audio_generation_queued_text(
                    current_part=index + 1,
                    total_parts=len(chunks),
                    queue_position=queued_position,
                )
            )
            await _enqueue_redis_audio_job(
                {
                    "type": "send_chunk",
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "session_id": session_id,
                    "status_message_id": _status_message_id(status_msg),
                }
            )
            return

        except asyncio.QueueFull:
            logger.warning(
                "ReadingService: Redis audio queue is full user_id=%s",
                user_id,
            )
            await safe_delete_message(status_msg)
            await _finish_generation_if_session(user_id, session_id)
            await message.answer(AUDIO_QUEUE_FULL_TEXT)
            return

        except RedisError:
            logger.exception(
                "ReadingService: Redis audio queue failed; falling back to "
                "memory queue user_id=%s",
                user_id,
            )
            await safe_delete_message(status_msg)

    queue = _ensure_audio_generation_queue()
    queued_position = queue.qsize() + 1
    status_msg = await message.answer(
        build_audio_generation_queued_text(
            current_part=index + 1,
            total_parts=len(chunks),
            queue_position=queued_position,
        )
    )

    async def job() -> None:
        await _send_audio_chunk_now(
            message=message,
            user_id=user_id,
            expected_session_id=session_id,
            status_msg=status_msg,
        )

    try:
        queue.put_nowait(job)
    except asyncio.QueueFull:
        await safe_delete_message(status_msg)
        await _finish_generation_if_session(user_id, session_id)
        await message.answer(AUDIO_QUEUE_FULL_TEXT)
