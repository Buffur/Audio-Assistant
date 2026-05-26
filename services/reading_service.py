# Файл: services/reading_service.py

import asyncio
import logging
import uuid
from contextlib import suppress

from aiogram.types import Message
from services.reading import audio_queue as reading_audio_queue
from services.reading.application import (
    chunk_audio_service,
    export_audio_service,
    prefetch_service,
    privacy_service,
)
from services.reading.application.commands import (
    AudioFilesResult,
    ExportReadingAudioCommand,
    ExportReadingAudioNowCommand,
    PrefetchAudioJobCommand,
    ResolvePrefetchedAudioCommand,
    SendAudioChunkCommand,
    SendAudioChunkNowCommand,
    StartPrefetchCommand,
)
from services.reading.application.privacy_service import (
    cleanup_user_private_runtime_data,
    mark_user_data_deletion,
    purge_queued_audio_jobs_for_user,
    should_skip_deleted_user_job as _should_skip_deleted_user_job,
)
from services.reading.audio_job_executor import ReadingAudioJobExecutor
from services.reading.infrastructure.session_store import (
    cleanup_reading_session,
    finish_generation as _finish_generation,
    get_reading_session,
    get_reading_session_model,
    has_reading_session as _has_reading_session,
    set_reading_session,
    try_start_generation as _try_start_generation,
    update_reading_session,
)
from services.tts import generate_voice
from services.usage_limits_service import is_premium_user
from services.user_settings_service import (
    build_user_tts_provider_chain,
    get_effective_user_settings,
    get_effective_user_tts_provider,
)
from services.voice_selector import select_voice_for_text
from services.voice_sender import send_voice_files
from texts.messages import (
    ALL_PARTS_SENT_AFTER_SUMMARY_TEXT,
    ALL_PARTS_SENT_TEXT,
    AUDIO_QUEUE_FULL_TEXT,
    BACKGROUND_GENERATION_ERROR,
    CHUNK_AUDIO_GENERATION_ERROR,
)
from utils.text_checks import is_error_text

logger = logging.getLogger(__name__)

READING_AUDIO_QUEUE_FLUSH_TIMEOUT_SECONDS = (
    reading_audio_queue.READING_AUDIO_QUEUE_FLUSH_TIMEOUT_SECONDS
)
REDIS_AUDIO_QUEUE_BLPOP_TIMEOUT_SECONDS = (
    reading_audio_queue.REDIS_AUDIO_QUEUE_BLPOP_TIMEOUT_SECONDS
)
REDIS_PREFETCH_WAIT_SECONDS = prefetch_service.REDIS_PREFETCH_WAIT_SECONDS
READING_AUDIO_QUEUE_BACKEND = reading_audio_queue.READING_AUDIO_QUEUE_BACKEND
READING_AUDIO_QUEUE_REDIS_KEY = reading_audio_queue.READING_AUDIO_QUEUE_REDIS_KEY
READING_AUDIO_QUEUE_MAX_SIZE = reading_audio_queue.READING_AUDIO_QUEUE_MAX_SIZE
REDIS_AUDIO_QUEUE_PROCESSING_KEY = reading_audio_queue.REDIS_AUDIO_QUEUE_PROCESSING_KEY

AudioGenerationJob = reading_audio_queue.AudioGenerationJob
ReadingSession = dict[str, object]
SerializedAudioJob = reading_audio_queue.SerializedAudioJob
_audio_queue_ensure_redis_audio_generation_worker = (
    reading_audio_queue._ensure_redis_audio_generation_worker
)
_last_audio_queue_backend = READING_AUDIO_QUEUE_BACKEND
_last_audio_queue_redis_key = READING_AUDIO_QUEUE_REDIS_KEY
_last_audio_queue_max_size = READING_AUDIO_QUEUE_MAX_SIZE

PRIVACY_DELETE_MARKER_PREFIX = privacy_service.PRIVACY_DELETE_MARKER_PREFIX
PRIVACY_DELETE_MARKER_TTL_SECONDS = (
    privacy_service.PRIVACY_DELETE_MARKER_TTL_SECONDS
)
_get_user_data_deletion_timestamp = (
    privacy_service._get_user_data_deletion_timestamp
)
_privacy_delete_markers = privacy_service._privacy_delete_markers


def _use_redis_audio_queue() -> bool:
    _sync_audio_queue_compat_settings()
    return reading_audio_queue.use_redis_audio_queue()


def _sync_audio_queue_compat_settings() -> None:
    global READING_AUDIO_QUEUE_BACKEND
    global READING_AUDIO_QUEUE_REDIS_KEY
    global READING_AUDIO_QUEUE_MAX_SIZE
    global REDIS_AUDIO_QUEUE_PROCESSING_KEY
    global _last_audio_queue_backend
    global _last_audio_queue_redis_key
    global _last_audio_queue_max_size

    READING_AUDIO_QUEUE_BACKEND = _select_audio_queue_compat_value(
        READING_AUDIO_QUEUE_BACKEND,
        reading_audio_queue.READING_AUDIO_QUEUE_BACKEND,
        _last_audio_queue_backend,
    )
    READING_AUDIO_QUEUE_REDIS_KEY = _select_audio_queue_compat_value(
        READING_AUDIO_QUEUE_REDIS_KEY,
        reading_audio_queue.READING_AUDIO_QUEUE_REDIS_KEY,
        _last_audio_queue_redis_key,
    )
    READING_AUDIO_QUEUE_MAX_SIZE = _select_audio_queue_compat_value(
        READING_AUDIO_QUEUE_MAX_SIZE,
        reading_audio_queue.READING_AUDIO_QUEUE_MAX_SIZE,
        _last_audio_queue_max_size,
    )

    reading_audio_queue.READING_AUDIO_QUEUE_BACKEND = READING_AUDIO_QUEUE_BACKEND
    reading_audio_queue.READING_AUDIO_QUEUE_REDIS_KEY = READING_AUDIO_QUEUE_REDIS_KEY
    reading_audio_queue.READING_AUDIO_QUEUE_MAX_SIZE = READING_AUDIO_QUEUE_MAX_SIZE
    reading_audio_queue.REDIS_AUDIO_QUEUE_PROCESSING_KEY = (
        f"{READING_AUDIO_QUEUE_REDIS_KEY}:processing"
    )
    REDIS_AUDIO_QUEUE_PROCESSING_KEY = reading_audio_queue.REDIS_AUDIO_QUEUE_PROCESSING_KEY
    _last_audio_queue_backend = READING_AUDIO_QUEUE_BACKEND
    _last_audio_queue_redis_key = READING_AUDIO_QUEUE_REDIS_KEY
    _last_audio_queue_max_size = READING_AUDIO_QUEUE_MAX_SIZE


def _select_audio_queue_compat_value(service_value, queue_value, last_value):
    service_changed = service_value != last_value
    queue_changed = queue_value != last_value

    if service_changed and not queue_changed:
        return service_value

    if queue_changed and not service_changed:
        return queue_value

    return service_value


def _ensure_redis_audio_generation_worker() -> None:
    _sync_audio_queue_compat_settings()
    _audio_queue_ensure_redis_audio_generation_worker(_run_serialized_audio_job)


def _install_redis_worker_compat_hook() -> None:
    def ensure_worker(_job_handler) -> None:
        _ensure_redis_audio_generation_worker()

    reading_audio_queue._ensure_redis_audio_generation_worker = ensure_worker


async def _run_prefetch_audio_job(job: SerializedAudioJob) -> None:
    await prefetch_service.run_prefetch_audio_job(
        PrefetchAudioJobCommand.from_serialized_job(job)
    )


def _build_audio_job_executor() -> ReadingAudioJobExecutor:
    return ReadingAudioJobExecutor(
        should_skip_deleted_user_job=_should_skip_deleted_user_job,
        run_prefetch_audio_job=_run_prefetch_audio_job,
        send_audio_chunk_now=_send_audio_chunk_now,
        export_reading_audio_now=_export_reading_audio_now,
    )


async def _run_serialized_audio_job(bot, job: SerializedAudioJob) -> None:
    await _build_audio_job_executor().run(bot, job)


async def start_reading_audio_workers() -> None:
    await reading_audio_queue.start_audio_workers(_run_serialized_audio_job)


async def _redis_audio_queue_position() -> int:
    _sync_audio_queue_compat_settings()
    return await reading_audio_queue.redis_audio_queue_position()


async def _enqueue_redis_audio_job(job: SerializedAudioJob) -> None:
    _sync_audio_queue_compat_settings()
    _install_redis_worker_compat_hook()
    await reading_audio_queue.enqueue_redis_audio_job(
        _normalize_legacy_audio_job(job),
        _run_serialized_audio_job,
    )


def _normalize_legacy_audio_job(job: SerializedAudioJob) -> SerializedAudioJob:
    job_type = str(job.get("type") or "")

    if job_type in {"send_chunk", "export_audio"} and "status_message_id" not in job:
        normalized_job = dict(job)
        normalized_job["status_message_id"] = None
        return reading_audio_queue.validate_audio_job(normalized_job)

    return reading_audio_queue.validate_audio_job(job)


async def purge_queued_audio_jobs_for_user(user_id: int) -> int:
    _sync_audio_queue_compat_settings()
    return await reading_audio_queue.purge_queued_audio_jobs_for_user(user_id)


def _ensure_audio_generation_queue() -> asyncio.Queue[AudioGenerationJob]:
    return reading_audio_queue.ensure_memory_audio_generation_queue()


def _memory_audio_queue_position() -> int:
    return reading_audio_queue.memory_audio_queue_position()


def _enqueue_memory_audio_job(job: AudioGenerationJob) -> None:
    reading_audio_queue.enqueue_memory_audio_job(job)


async def close_reading_audio_queue(
    timeout_seconds: float = READING_AUDIO_QUEUE_FLUSH_TIMEOUT_SECONDS,
) -> None:
    await reading_audio_queue.close_audio_queue(timeout_seconds=timeout_seconds)


async def safe_delete_message(message: Message | None) -> None:
    """
    Безпечно видаляє повідомлення.
    Якщо Telegram не дозволив видалення — просто ігноруємо.
    """
    if message is None:
        return

    with suppress(Exception):
        await message.delete()


async def _finish_generation_if_session(
    user_id: int,
    session_id: str | None,
) -> None:
    session = await get_reading_session_model(user_id)

    if session and (session_id is None or session.session_id == session_id):
        await update_reading_session(user_id, is_generating=False)


async def cleanup_session(user_id: int) -> None:
    """
    Public wrapper для handlers.
    """
    await cleanup_reading_session(user_id)


def create_reading_session(
    *,
    chunks: list[str],
    catalog_document_id: object | None = None,
    summary_text: str | None = None,
    summary_voice_file_ids: list[str] | None = None,
    summary_voice_voice: str | None = None,
    summary_voice_rate: str | None = None,
    summary_voice_provider: str | None = None,
) -> ReadingSession:
    session: ReadingSession = {
        "session_id": uuid.uuid4().hex[:12],
        "chunks": chunks,
        "index": 0,
        "is_generating": True,
        "prefetch_task": None,
    }

    if catalog_document_id is not None:
        session["catalog_document_id"] = catalog_document_id

    normalized_summary_text = (summary_text or "").strip()

    if normalized_summary_text:
        session["summary_text"] = normalized_summary_text
        session["summary_delivered"] = False

    if summary_voice_file_ids:
        session["summary_voice_file_ids"] = summary_voice_file_ids
        session["summary_voice_voice"] = summary_voice_voice
        session["summary_voice_rate"] = summary_voice_rate
        session["summary_voice_provider"] = summary_voice_provider

    return session


async def is_audio_generation_active(user_id: int) -> bool:
    session = await get_reading_session_model(user_id)

    return bool(session and session.is_generating)


async def get_current_reading_session(user_id: int) -> ReadingSession | None:
    return await get_reading_session(user_id)


async def has_current_reading_session(user_id: int) -> bool:
    return await _has_reading_session(user_id)


async def try_start_reading_generation(user_id: int) -> bool:
    return await _try_start_generation(user_id)


async def finish_reading_generation(user_id: int) -> None:
    await _finish_generation(user_id)


async def update_current_reading_session(user_id: int, **updates: object) -> None:
    await update_reading_session(user_id, **updates)


async def start_reading_session(
    *,
    user_id: int,
    chunks: list[str],
    catalog_document_id: object | None = None,
    summary_text: str | None = None,
    summary_voice_file_ids: list[str] | None = None,
    summary_voice_voice: str | None = None,
    summary_voice_rate: str | None = None,
    summary_voice_provider: str | None = None,
    cleanup_existing: bool = True,
) -> ReadingSession:
    if cleanup_existing:
        await cleanup_session(user_id)

    session = create_reading_session(
        chunks=chunks,
        catalog_document_id=catalog_document_id,
        summary_text=summary_text,
        summary_voice_file_ids=summary_voice_file_ids,
        summary_voice_voice=summary_voice_voice,
        summary_voice_rate=summary_voice_rate,
        summary_voice_provider=summary_voice_provider,
    )

    await set_reading_session(
        user_id=user_id,
        session=session,
    )

    return session


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
    job_created_at: float | None = None,
) -> None:
    await export_audio_service.export_reading_audio_now(
        ExportReadingAudioNowCommand(
            message=message,
            user_id=user_id,
            expected_session_id=expected_session_id,
            status_msg=status_msg,
            job_created_at=job_created_at,
        ),
        finish_generation_if_session=_finish_generation_if_session,
        should_skip_deleted_user_job=_should_skip_deleted_user_job,
        send_audio_files=_send_audio_files,
    )


async def _export_reading_audio_now_from_command(
    command: ExportReadingAudioNowCommand,
) -> None:
    await _export_reading_audio_now(
        message=command.message,
        user_id=command.user_id,
        expected_session_id=command.expected_session_id,
        status_msg=command.status_msg,
        job_created_at=command.job_created_at,
    )


async def export_reading_audio(
    message: Message,
    user_id: int,
    expected_session_id: str | None = None,
) -> None:
    await export_audio_service.export_reading_audio(
        ExportReadingAudioCommand(
            message=message,
            user_id=user_id,
            expected_session_id=expected_session_id,
        ),
        cleanup_session=cleanup_session,
        finish_generation_if_session=_finish_generation_if_session,
        use_redis_audio_queue=_use_redis_audio_queue,
        redis_audio_queue_position=_redis_audio_queue_position,
        enqueue_redis_audio_job=_enqueue_redis_audio_job,
        memory_audio_queue_position=_memory_audio_queue_position,
        enqueue_memory_audio_job=_enqueue_memory_audio_job,
        export_reading_audio_now=_export_reading_audio_now_from_command,
    )


async def reply_with_voice(
    message: Message,
    user_id: int,
    text: str,
    status_msg: Message | None = None,
) -> None:
    """
    Надсилає службовий текст голосом.
    Помилки для користувача завжди залишаються текстовими.
    Якщо TTS не спрацював — надсилає звичайний текст.
    """
    await safe_delete_message(status_msg)

    if is_error_text(text):
        await message.answer(text)
        return

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
    session,
    chunk_text: str,
    voice: str,
    rate: str,
    provider_chain: list[str],
    current_part: int,
    total_parts: int,
    status_msg: Message | None = None,
) -> list[str]:
    result = await prefetch_service.get_audio_from_prefetch_or_generate(
        ResolvePrefetchedAudioCommand(
            message=message,
            user_id=user_id,
            session=session,
            chunk_text=chunk_text,
            voice=voice,
            rate=rate,
            provider_chain=provider_chain,
            current_part=current_part,
            total_parts=total_parts,
            status_msg=status_msg,
        )
    )
    return result.audio_files


async def _get_audio_from_prefetch_or_generate_from_command(
    command: ResolvePrefetchedAudioCommand,
) -> AudioFilesResult:
    result = await _get_audio_from_prefetch_or_generate(
        message=command.message,
        user_id=command.user_id,
        session=command.session,
        chunk_text=command.chunk_text,
        voice=command.voice,
        rate=command.rate,
        provider_chain=command.provider_chain,
        current_part=command.current_part,
        total_parts=command.total_parts,
        status_msg=command.status_msg,
    )

    if isinstance(result, AudioFilesResult):
        return result

    return AudioFilesResult(audio_files=list(result))


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
    await prefetch_service.start_prefetch_next_chunk(
        StartPrefetchCommand(
            user_id=user_id,
            session_id=session_id,
            chunks=chunks,
            next_index=next_index,
            voice_pref=voice_pref,
            rate=rate,
            tts_provider=tts_provider,
        ),
        enqueue_redis_audio_job=_enqueue_redis_audio_job,
    )


async def _start_prefetch_next_chunk_from_command(
    command: StartPrefetchCommand,
) -> None:
    await _start_prefetch_next_chunk(
        user_id=command.user_id,
        session_id=command.session_id,
        chunks=command.chunks,
        next_index=command.next_index,
        voice_pref=command.voice_pref,
        rate=command.rate,
        tts_provider=command.tts_provider,
    )


async def _send_audio_chunk_now(
    message: Message,
    user_id: int,
    expected_session_id: str | None,
    status_msg: Message | None,
    job_created_at: float | None = None,
) -> None:
    await chunk_audio_service.send_audio_chunk_now(
        SendAudioChunkNowCommand(
            message=message,
            user_id=user_id,
            expected_session_id=expected_session_id,
            status_msg=status_msg,
            job_created_at=job_created_at,
        ),
        cleanup_session=cleanup_session,
        finish_generation_if_session=_finish_generation_if_session,
        should_skip_deleted_user_job=_should_skip_deleted_user_job,
        get_audio_from_prefetch_or_generate=(
            _get_audio_from_prefetch_or_generate_from_command
        ),
        start_prefetch_next_chunk=_start_prefetch_next_chunk_from_command,
        send_audio_files=_send_audio_files,
        get_effective_user_settings=get_effective_user_settings,
        get_effective_user_tts_provider=get_effective_user_tts_provider,
        is_premium_user=is_premium_user,
        select_voice_for_text=select_voice_for_text,
    )


async def _send_audio_chunk_now_from_command(
    command: SendAudioChunkNowCommand,
) -> None:
    await _send_audio_chunk_now(
        message=command.message,
        user_id=command.user_id,
        expected_session_id=command.expected_session_id,
        status_msg=command.status_msg,
        job_created_at=command.job_created_at,
    )


async def send_audio_chunk(message: Message, user_id: int) -> None:
    await chunk_audio_service.send_audio_chunk(
        SendAudioChunkCommand(
            message=message,
            user_id=user_id,
        ),
        cleanup_session=cleanup_session,
        finish_generation_if_session=_finish_generation_if_session,
        use_redis_audio_queue=_use_redis_audio_queue,
        redis_audio_queue_position=_redis_audio_queue_position,
        enqueue_redis_audio_job=_enqueue_redis_audio_job,
        memory_audio_queue_position=_memory_audio_queue_position,
        enqueue_memory_audio_job=_enqueue_memory_audio_job,
        send_audio_chunk_now=_send_audio_chunk_now_from_command,
    )
