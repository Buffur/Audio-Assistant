import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from redis.exceptions import RedisError

from services.reading import audio_queue
from services.reading.application import privacy_service
from services.reading.infrastructure.session_store import (
    get_reading_session,
    update_reading_session,
)
from services.tts import generate_voice
from services.user_settings_service import build_user_tts_provider_chain
from services.voice_selector import select_voice_for_text
from services.voice_sender import safe_remove_file
from texts.messages import (
    build_generating_audio_progress_text,
    build_generating_chunk_text,
    build_loading_chunk_text,
)

logger = logging.getLogger(__name__)

REDIS_PREFETCH_WAIT_SECONDS = 3.0

ReadingSession = dict[str, object]
EnqueueRedisAudioJob = Callable[[audio_queue.SerializedAudioJob], Awaitable[None]]


async def _safe_delete_message(message: Any | None) -> None:
    if message is None:
        return

    with suppress(Exception):
        await message.delete()


async def _safe_edit_message(message: Any | None, text: str) -> None:
    if message is None:
        return

    with suppress(Exception):
        await message.edit_text(text)


def _is_same_session(session: ReadingSession | None, session_id: str | None) -> bool:
    if not session:
        return False

    if session_id is None:
        return True

    return session.get("session_id") == session_id


def _cleanup_audio_files(audio_files: list[str]) -> None:
    for audio_path in audio_files:
        safe_remove_file(audio_path)


async def run_prefetch_audio_job(job: audio_queue.SerializedAudioJob) -> None:
    user_id = int(job["user_id"])
    job_created_at = float(job.get("created_at") or 0)
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

    if await privacy_service.should_skip_deleted_user_job(user_id, job_created_at):
        return

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

        if await privacy_service.should_skip_deleted_user_job(user_id, job_created_at):
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
            "ReadingPrefetchService: Redis prefetch job failed user_id=%s chunk_index=%s",
            user_id,
            chunk_index,
        )
        if await privacy_service.should_skip_deleted_user_job(user_id, job_created_at):
            return

        await update_reading_session(
            user_id,
            prefetch_state="failed",
            prefetch_index=chunk_index,
            prefetch_audio_files=[],
            prefetch_error=str(error),
        )

    finally:
        _cleanup_audio_files(audio_files)


async def get_audio_from_prefetch_or_generate(
    *,
    message: Any,
    user_id: int,
    session: ReadingSession,
    chunk_text: str,
    voice: str,
    rate: str,
    provider_chain: list[str],
    current_part: int,
    total_parts: int,
    status_msg: Any | None = None,
) -> list[str]:
    current_index = current_part - 1
    prefetch_state = str(session.get("prefetch_state") or "")
    prefetch_index = session.get("prefetch_index")

    if prefetch_index == current_index and prefetch_state in {"queued", "running"}:
        await _safe_edit_message(
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
        await _safe_delete_message(status_msg)
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
            await _safe_edit_message(
                status_msg,
                build_loading_chunk_text(current_part, total_parts),
            )

        try:
            audio_files = await prefetch_task

        except asyncio.CancelledError:
            logger.info(
                "ReadingPrefetchService: prefetch_task cancelled, generating manually user_id=%s",
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
                "ReadingPrefetchService: prefetch_task failed, generating manually user_id=%s",
                user_id,
            )
            audio_files = await generate_voice(
                chunk_text,
                voice,
                rate,
                provider_chain=provider_chain,
            )

        await update_reading_session(user_id, prefetch_task=None)
        await _safe_delete_message(status_msg)
        return audio_files

    await _safe_edit_message(
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

        await _safe_edit_message(
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
        await _safe_delete_message(status_msg)


async def start_prefetch_next_chunk(
    *,
    user_id: int,
    session_id: str,
    chunks: list[str],
    next_index: int,
    voice_pref: str,
    rate: str,
    tts_provider: str,
    enqueue_redis_audio_job: EnqueueRedisAudioJob,
) -> None:
    if next_index >= len(chunks):
        return

    next_chunk = chunks[next_index]
    next_voice = select_voice_for_text(next_chunk, voice_pref)
    provider_chain = build_user_tts_provider_chain(
        tts_provider,
        voice=next_voice,
    )

    if audio_queue.use_redis_audio_queue():
        await update_reading_session(
            user_id,
            prefetch_state="queued",
            prefetch_index=next_index,
            prefetch_audio_files=[],
            prefetch_error="",
        )

        try:
            await enqueue_redis_audio_job(
                audio_queue.build_prefetch_chunk_job(
                    user_id=user_id,
                    session_id=session_id,
                    chunk_index=next_index,
                    chunk_text=next_chunk,
                    voice=next_voice,
                    rate=rate,
                    provider_chain=provider_chain,
                    created_at=time.time(),
                )
            )
            return
        except (RedisError, asyncio.QueueFull):
            logger.exception(
                "ReadingPrefetchService: failed to enqueue Redis prefetch job user_id=%s",
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
