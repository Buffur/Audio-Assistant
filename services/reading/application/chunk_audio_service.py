import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from redis.exceptions import RedisError

from keyboards.reading import reading_navigation_keyboard
from services.reading import audio_queue
from services.reading.infrastructure.session_store import (
    get_reading_session,
    update_reading_session,
)
from services.user_settings_service import build_user_tts_provider_chain
from services.voice_sender import safe_remove_file
from texts.messages import (
    ALL_PARTS_SENT_AFTER_SUMMARY_TEXT,
    ALL_PARTS_SENT_TEXT,
    AUDIO_QUEUE_FULL_TEXT,
    BACKGROUND_GENERATION_ERROR,
    CHUNK_AUDIO_GENERATION_ERROR,
    SESSION_NOT_FOUND_OR_FINISHED_TEXT,
    build_audio_generation_queued_text,
    build_part_audio_caption,
    build_part_caption,
)

logger = logging.getLogger(__name__)

NO_READING_TEXT = "\u274c \u0423 \u0441\u0435\u0441\u0456\u0457 \u043d\u0435\u043c\u0430\u0454 \u0442\u0435\u043a\u0441\u0442\u0443 \u0434\u043b\u044f \u0447\u0438\u0442\u0430\u043d\u043d\u044f."
ALL_PARTS_ALREADY_SENT_TEXT = "\u2705 \u0412\u0441\u0456 \u0447\u0430\u0441\u0442\u0438\u043d\u0438 \u0432\u0436\u0435 \u0431\u0443\u043b\u0438 \u043d\u0430\u0434\u0456\u0441\u043b\u0430\u043d\u0456."

ReadingSession = dict[str, object]
AudioGenerationJob = audio_queue.AudioGenerationJob
SerializedAudioJob = audio_queue.SerializedAudioJob

AsyncIntSupplier = Callable[[], Awaitable[int]]
IntSupplier = Callable[[], int]
BoolSupplier = Callable[[], bool]
EnqueueRedisAudioJob = Callable[[SerializedAudioJob], Awaitable[None]]
EnqueueMemoryAudioJob = Callable[[AudioGenerationJob], None]
FinishGenerationIfSession = Callable[[int, str | None], Awaitable[None]]
CleanupSession = Callable[[int], Awaitable[None]]
ShouldSkipDeletedUserJob = Callable[[int, float | None], Awaitable[bool]]
GetAudioFromPrefetchOrGenerate = Callable[..., Awaitable[list[str]]]
StartPrefetchNextChunk = Callable[..., Awaitable[None]]
SendAudioFiles = Callable[..., Awaitable[None]]
GetEffectiveUserSettings = Callable[[int], Awaitable[tuple[str, str]]]
GetEffectiveUserTtsProvider = Callable[[int], Awaitable[str]]
IsPremiumUser = Callable[[int], Awaitable[bool]]
SelectVoiceForText = Callable[[str, str], str]


async def safe_delete_message(message: Any | None) -> None:
    if message is None:
        return

    with suppress(Exception):
        await message.delete()


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

    return session.get("session_id") == session_id


def _cleanup_audio_files(audio_files: list[str]) -> None:
    for audio_path in audio_files:
        safe_remove_file(audio_path)


async def send_audio_chunk_now(
    *,
    message: Any,
    user_id: int,
    expected_session_id: str | None,
    status_msg: Any | None,
    job_created_at: float | None = None,
    cleanup_session: CleanupSession,
    finish_generation_if_session: FinishGenerationIfSession,
    should_skip_deleted_user_job: ShouldSkipDeletedUserJob,
    get_audio_from_prefetch_or_generate: GetAudioFromPrefetchOrGenerate,
    start_prefetch_next_chunk: StartPrefetchNextChunk,
    send_audio_files: SendAudioFiles,
    get_effective_user_settings: GetEffectiveUserSettings,
    get_effective_user_tts_provider: GetEffectiveUserTtsProvider,
    is_premium_user: IsPremiumUser,
    select_voice_for_text: SelectVoiceForText,
) -> None:
    if await should_skip_deleted_user_job(user_id, job_created_at):
        await safe_delete_message(status_msg)
        return

    session = await get_reading_session(user_id)

    if not _is_same_session(session, expected_session_id):
        await safe_delete_message(status_msg)
        return

    chunks = session.get("chunks") or []
    index = int(session.get("index", 0))
    current_session_id = str(session.get("session_id", "legacy"))

    if not chunks:
        await cleanup_session(user_id)
        await message.answer(NO_READING_TEXT)
        return

    if index >= len(chunks):
        await cleanup_session(user_id)
        await message.answer(ALL_PARTS_ALREADY_SENT_TEXT)
        return

    chunk_text = chunks[index]

    voice_pref, rate = await get_effective_user_settings(user_id)
    tts_provider = await get_effective_user_tts_provider(user_id)
    voice = select_voice_for_text(chunk_text, voice_pref)
    provider_chain = build_user_tts_provider_chain(tts_provider, voice=voice)

    try:
        audio_files = await get_audio_from_prefetch_or_generate(
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
                "ReadingChunkAudioService: TTS returned empty audio list user_id=%s index=%s",
                user_id,
                index,
            )
            await message.answer(CHUNK_AUDIO_GENERATION_ERROR)
            return

        current_session = await get_reading_session(user_id)

        if not _is_same_session(current_session, expected_session_id):
            _cleanup_audio_files(audio_files)
            return

        if await should_skip_deleted_user_job(user_id, job_created_at):
            _cleanup_audio_files(audio_files)
            await safe_delete_message(status_msg)
            return

        new_index = index + 1
        has_next = new_index < len(chunks)
        summary_already_delivered = bool(current_session.get("summary_delivered"))

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
            show_summary_button=not summary_already_delivered,
        )
        part_caption = build_part_caption(index + 1, len(chunks))

        if await should_skip_deleted_user_job(user_id, job_created_at):
            _cleanup_audio_files(audio_files)
            await safe_delete_message(status_msg)
            return

        await send_audio_files(
            message=message,
            audio_files=audio_files,
            caption=part_caption,
            reply_markup=None if not has_next else keyboard,
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
                if summary_already_delivered
                else ALL_PARTS_SENT_TEXT,
                reply_markup=keyboard,
            )
            return

        await start_prefetch_next_chunk(
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
            "ReadingChunkAudioService: failed to send audio chunk user_id=%s index=%s",
            user_id,
            index,
        )
        await message.answer(BACKGROUND_GENERATION_ERROR)

    finally:
        await finish_generation_if_session(user_id, expected_session_id)


async def send_audio_chunk(
    *,
    message: Any,
    user_id: int,
    cleanup_session: CleanupSession,
    finish_generation_if_session: FinishGenerationIfSession,
    use_redis_audio_queue: BoolSupplier,
    redis_audio_queue_position: AsyncIntSupplier,
    enqueue_redis_audio_job: EnqueueRedisAudioJob,
    memory_audio_queue_position: IntSupplier,
    enqueue_memory_audio_job: EnqueueMemoryAudioJob,
    send_audio_chunk_now: Callable[..., Awaitable[None]],
) -> None:
    session = await get_reading_session(user_id)

    if not session:
        await message.answer(SESSION_NOT_FOUND_OR_FINISHED_TEXT)
        return

    chunks = session.get("chunks") or []
    index = int(session.get("index", 0))
    session_id = str(session.get("session_id", "legacy"))

    if not chunks:
        await cleanup_session(user_id)
        await message.answer(NO_READING_TEXT)
        return

    if index >= len(chunks):
        await cleanup_session(user_id)
        await message.answer(ALL_PARTS_ALREADY_SENT_TEXT)
        return

    await update_reading_session(user_id, is_generating=True)

    chat_id = _message_chat_id(message)
    job_created_at = time.time()

    if use_redis_audio_queue() and chat_id is not None:
        status_msg = None

        try:
            queued_position = await redis_audio_queue_position()
            status_msg = await message.answer(
                build_audio_generation_queued_text(
                    current_part=index + 1,
                    total_parts=len(chunks),
                    queue_position=queued_position,
                )
            )
            await enqueue_redis_audio_job(
                audio_queue.build_send_chunk_job(
                    user_id=user_id,
                    chat_id=chat_id,
                    session_id=session_id,
                    status_message_id=_status_message_id(status_msg),
                    created_at=job_created_at,
                )
            )
            return

        except asyncio.QueueFull:
            logger.warning(
                "ReadingChunkAudioService: Redis audio queue is full user_id=%s",
                user_id,
            )
            await safe_delete_message(status_msg)
            await finish_generation_if_session(user_id, session_id)
            await message.answer(AUDIO_QUEUE_FULL_TEXT)
            return

        except RedisError:
            logger.exception(
                "ReadingChunkAudioService: Redis audio queue failed user_id=%s",
                user_id,
            )
            await safe_delete_message(status_msg)
            await finish_generation_if_session(user_id, session_id)
            await message.answer(BACKGROUND_GENERATION_ERROR)
            return

    queued_position = memory_audio_queue_position()
    status_msg = await message.answer(
        build_audio_generation_queued_text(
            current_part=index + 1,
            total_parts=len(chunks),
            queue_position=queued_position,
        )
    )

    async def job() -> None:
        await send_audio_chunk_now(
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
