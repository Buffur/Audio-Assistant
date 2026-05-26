import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from redis.exceptions import RedisError

from config import (
    EXPORT_AUDIO_CROSSFADE_MS,
    EXPORT_AUDIO_MAX_SIZE_MB,
    EXPORT_AUDIO_SMOOTH_MERGE_ENABLED,
)
from services.reading import audio_queue
from services.reading.domain.models import ReadingSession
from services.reading.infrastructure.session_store import (
    get_reading_session_model,
    update_reading_session,
)
from services.tts import generate_voice
from services.user_settings_service import (
    build_user_tts_provider_chain,
    get_effective_user_settings,
    get_effective_user_tts_provider,
)
from services.voice_selector import select_voice_for_text
from services.voice_sender import safe_remove_file
from texts.messages import (
    AUDIO_QUEUE_FULL_TEXT,
    EXPORT_AUDIO_CAPTION_TEXT,
    EXPORT_AUDIO_CONCATENATING_TEXT,
    EXPORT_AUDIO_GENERATION_ERROR,
    SESSION_NOT_FOUND_OR_FINISHED_TEXT,
    build_export_audio_part_text,
    build_export_audio_progress_text,
    build_export_audio_queued_text,
    build_export_audio_too_large_text,
)
from utils.audio import concat_ogg_files

logger = logging.getLogger(__name__)

AudioGenerationJob = audio_queue.AudioGenerationJob
SerializedAudioJob = audio_queue.SerializedAudioJob

AsyncIntSupplier = Callable[[], Awaitable[int]]
IntSupplier = Callable[[], int]
BoolSupplier = Callable[[], bool]
CleanupSession = Callable[[int], Awaitable[None]]
EnqueueRedisAudioJob = Callable[[SerializedAudioJob], Awaitable[None]]
EnqueueMemoryAudioJob = Callable[[AudioGenerationJob], None]
ExportAudioNow = Callable[..., Awaitable[None]]
FinishGenerationIfSession = Callable[[int, str | None], Awaitable[None]]
SendAudioFiles = Callable[..., Awaitable[None]]
ShouldSkipDeletedUserJob = Callable[[int, float | None], Awaitable[bool]]


async def safe_delete_message(message: Any | None) -> None:
    if message is None:
        return

    with suppress(Exception):
        await message.delete()


async def safe_edit_message(message: Any | None, text: str) -> None:
    if message is None:
        return

    with suppress(Exception):
        await message.edit_text(text)


def _message_chat_id(message: Any) -> int | None:
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)

    if isinstance(chat_id, int):
        return chat_id

    return None


def _status_message_id(message: Any | None) -> int | None:
    message_id = getattr(message, "message_id", None)

    if isinstance(message_id, int):
        return message_id

    return None


def _is_same_session(session: ReadingSession | None, session_id: str | None) -> bool:
    if not session:
        return False

    if session_id is None:
        return True

    return session.session_id == session_id


def _export_max_size_bytes() -> int:
    return EXPORT_AUDIO_MAX_SIZE_MB * 1024 * 1024


def _file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 * 1024)


def _cleanup_audio_files(audio_files: list[str]) -> None:
    for audio_path in audio_files:
        safe_remove_file(audio_path)


async def export_reading_audio_now(
    *,
    message: Any,
    user_id: int,
    expected_session_id: str | None,
    status_msg: Any | None,
    job_created_at: float | None = None,
    finish_generation_if_session: FinishGenerationIfSession,
    should_skip_deleted_user_job: ShouldSkipDeletedUserJob,
    send_audio_files: SendAudioFiles,
) -> None:
    if await should_skip_deleted_user_job(user_id, job_created_at):
        await safe_delete_message(status_msg)
        return

    session = await get_reading_session_model(user_id)

    if not _is_same_session(session, expected_session_id):
        await safe_delete_message(status_msg)
        return

    chunks = session.chunks

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
            if await should_skip_deleted_user_job(user_id, job_created_at):
                await safe_delete_message(status_msg)
                return

            current_session = await get_reading_session_model(user_id)

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

            if await should_skip_deleted_user_job(user_id, job_created_at):
                _cleanup_audio_files(audio_files)
                await safe_delete_message(status_msg)
                return

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

        if await should_skip_deleted_user_job(user_id, job_created_at):
            await safe_delete_message(status_msg)
            return

        current_session = await get_reading_session_model(user_id)

        if not _is_same_session(current_session, expected_session_id):
            await safe_delete_message(status_msg)
            return

        await safe_delete_message(status_msg)

        await send_audio_files(
            message=message,
            audio_files=[combined_audio_file],
            caption=EXPORT_AUDIO_CAPTION_TEXT,
        )
        combined_audio_file = None

    except Exception:
        logger.exception(
            "ReadingExportAudioService: full audio export failed user_id=%s",
            user_id,
        )
        await safe_delete_message(status_msg)
        await message.answer(EXPORT_AUDIO_GENERATION_ERROR)

    finally:
        _cleanup_audio_files(generated_audio_files)
        safe_remove_file(combined_audio_file)
        await finish_generation_if_session(user_id, expected_session_id)


async def export_reading_audio(
    *,
    message: Any,
    user_id: int,
    expected_session_id: str | None = None,
    cleanup_session: CleanupSession,
    finish_generation_if_session: FinishGenerationIfSession,
    use_redis_audio_queue: BoolSupplier,
    redis_audio_queue_position: AsyncIntSupplier,
    enqueue_redis_audio_job: EnqueueRedisAudioJob,
    memory_audio_queue_position: IntSupplier,
    enqueue_memory_audio_job: EnqueueMemoryAudioJob,
    export_reading_audio_now: ExportAudioNow,
) -> None:
    session = await get_reading_session_model(user_id)

    if not _is_same_session(session, expected_session_id):
        await message.answer(SESSION_NOT_FOUND_OR_FINISHED_TEXT)
        return

    chunks = session.chunks
    session_id = session.session_id

    if not chunks:
        await cleanup_session(user_id)
        await message.answer(SESSION_NOT_FOUND_OR_FINISHED_TEXT)
        return

    await update_reading_session(user_id, is_generating=True)

    chat_id = _message_chat_id(message)
    job_created_at = time.time()

    if use_redis_audio_queue() and chat_id is not None:
        status_msg = None

        try:
            queued_position = await redis_audio_queue_position()
            status_msg = await message.answer(
                build_export_audio_queued_text(
                    total_parts=len(chunks),
                    queue_position=queued_position,
                )
            )
            await enqueue_redis_audio_job(
                audio_queue.build_export_audio_job(
                    user_id=user_id,
                    chat_id=chat_id,
                    session_id=session_id,
                    status_message_id=_status_message_id(status_msg),
                    created_at=job_created_at,
                )
            )
            return

        except asyncio.QueueFull:
            await safe_delete_message(status_msg)
            await finish_generation_if_session(user_id, session_id)
            await message.answer(AUDIO_QUEUE_FULL_TEXT)
            return

        except RedisError:
            logger.exception(
                "ReadingExportAudioService: Redis export queue failed user_id=%s",
                user_id,
            )
            await safe_delete_message(status_msg)
            await finish_generation_if_session(user_id, session_id)
            await message.answer(EXPORT_AUDIO_GENERATION_ERROR)
            return

    queued_position = memory_audio_queue_position()
    status_msg = await message.answer(
        build_export_audio_queued_text(
            total_parts=len(chunks),
            queue_position=queued_position,
        )
    )

    async def job() -> None:
        await export_reading_audio_now(
            message=message,
            user_id=user_id,
            expected_session_id=session_id,
            status_msg=status_msg,
            job_created_at=job_created_at,
        )

    try:
        enqueue_memory_audio_job(job)
    except asyncio.QueueFull:
        await safe_delete_message(status_msg)
        await finish_generation_if_session(user_id, session_id)
        await message.answer(AUDIO_QUEUE_FULL_TEXT)
