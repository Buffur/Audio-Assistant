import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict, cast

from aiogram import Bot
from redis.exceptions import RedisError

from config import (
    BOT_TOKEN,
    READING_AUDIO_QUEUE_BACKEND,
    READING_AUDIO_QUEUE_MAX_SIZE,
    READING_AUDIO_QUEUE_REDIS_KEY,
)
from services.redis_client import get_redis_client

logger = logging.getLogger(__name__)

READING_AUDIO_QUEUE_FLUSH_TIMEOUT_SECONDS = 10.0
REDIS_AUDIO_QUEUE_BLPOP_TIMEOUT_SECONDS = 5
REDIS_AUDIO_QUEUE_PROCESSING_KEY = f"{READING_AUDIO_QUEUE_REDIS_KEY}:processing"

AudioGenerationJob = Callable[[], Awaitable[None]]


class BaseSerializedAudioJob(TypedDict):
    type: str
    user_id: int
    created_at: NotRequired[float]
    job_id: NotRequired[str]


class SendChunkAudioJob(BaseSerializedAudioJob):
    type: Literal["send_chunk"]
    chat_id: int
    session_id: str
    status_message_id: int | None


class ExportAudioJob(BaseSerializedAudioJob):
    type: Literal["export_audio"]
    chat_id: int
    session_id: str
    status_message_id: int | None


class PrefetchChunkAudioJob(BaseSerializedAudioJob):
    type: Literal["prefetch_chunk"]
    session_id: str
    chunk_index: int
    chunk_text: str
    voice: str
    rate: str
    provider_chain: list[str]


SerializedAudioJob = SendChunkAudioJob | ExportAudioJob | PrefetchChunkAudioJob
SerializedAudioJobHandler = Callable[[Bot, SerializedAudioJob], Awaitable[None]]


@dataclass(frozen=True)
class AudioQueueStats:
    backend: str
    max_size: int
    pending: int | None
    processing: int | None
    worker_running: bool
    degraded: bool = False
    error: str | None = None

    @property
    def is_full(self) -> bool | None:
        if self.pending is None:
            return None

        return self.pending >= self.max_size

    @property
    def available_capacity(self) -> int | None:
        if self.pending is None:
            return None

        return max(self.max_size - self.pending, 0)

    def as_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "max_size": self.max_size,
            "pending": self.pending,
            "processing": self.processing,
            "worker_running": self.worker_running,
            "degraded": self.degraded,
            "error": self.error,
            "is_full": self.is_full,
            "available_capacity": self.available_capacity,
        }

_audio_generation_queue: asyncio.Queue[AudioGenerationJob] | None = None
_audio_generation_worker_task: asyncio.Task | None = None
_redis_audio_generation_worker_task: asyncio.Task | None = None
_redis_audio_queue_recovered = False


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
            logger.exception("ReadingAudioQueue: background audio job failed")
        finally:
            queue.task_done()


def use_redis_audio_queue() -> bool:
    return READING_AUDIO_QUEUE_BACKEND == "redis"


def _memory_worker_running() -> bool:
    return (
        _audio_generation_worker_task is not None
        and not _audio_generation_worker_task.done()
    )


def _redis_worker_running() -> bool:
    return (
        _redis_audio_generation_worker_task is not None
        and not _redis_audio_generation_worker_task.done()
    )


def _set_created_at(
    job: SerializedAudioJob,
    created_at: float | None,
) -> SerializedAudioJob:
    if created_at is not None:
        job["created_at"] = created_at

    return job


def build_send_chunk_job(
    *,
    user_id: int,
    chat_id: int,
    session_id: str,
    status_message_id: int | None,
    created_at: float | None = None,
) -> SendChunkAudioJob:
    job: SendChunkAudioJob = {
        "type": "send_chunk",
        "user_id": user_id,
        "chat_id": chat_id,
        "session_id": session_id,
        "status_message_id": status_message_id,
    }

    return cast(SendChunkAudioJob, _set_created_at(job, created_at))


def build_export_audio_job(
    *,
    user_id: int,
    chat_id: int,
    session_id: str,
    status_message_id: int | None,
    created_at: float | None = None,
) -> ExportAudioJob:
    job: ExportAudioJob = {
        "type": "export_audio",
        "user_id": user_id,
        "chat_id": chat_id,
        "session_id": session_id,
        "status_message_id": status_message_id,
    }

    return cast(ExportAudioJob, _set_created_at(job, created_at))


def build_prefetch_chunk_job(
    *,
    user_id: int,
    session_id: str,
    chunk_index: int,
    chunk_text: str,
    voice: str,
    rate: str,
    provider_chain: list[str],
    created_at: float | None = None,
) -> PrefetchChunkAudioJob:
    job: PrefetchChunkAudioJob = {
        "type": "prefetch_chunk",
        "user_id": user_id,
        "session_id": session_id,
        "chunk_index": chunk_index,
        "chunk_text": chunk_text,
        "voice": voice,
        "rate": rate,
        "provider_chain": provider_chain,
    }

    return cast(PrefetchChunkAudioJob, _set_created_at(job, created_at))


def serialize_audio_job(job: SerializedAudioJob) -> str:
    payload = dict(job)
    payload.setdefault("job_id", uuid.uuid4().hex)
    payload.setdefault("created_at", time.time())
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


async def purge_queued_audio_jobs_for_user(user_id: int) -> int:
    if not use_redis_audio_queue():
        return 0

    try:
        client = await get_redis_client()
        removed_count = await client.eval(
            """
            local removed = 0

            for key_index = 1, #KEYS do
                local key = KEYS[key_index]
                local items = redis.call("LRANGE", key, 0, -1)

                redis.call("DEL", key)

                for _, item in ipairs(items) do
                    local ok, job = pcall(cjson.decode, item)

                    if ok and tostring(job["user_id"]) == ARGV[1] then
                        removed = removed + 1
                    else
                        redis.call("RPUSH", key, item)
                    end
                end
            end

            return removed
            """,
            2,
            READING_AUDIO_QUEUE_REDIS_KEY,
            REDIS_AUDIO_QUEUE_PROCESSING_KEY,
            str(user_id),
        )

        return int(removed_count or 0)

    except RedisError:
        logger.exception(
            "ReadingAudioQueue: failed to purge queued jobs user_id=%s",
            user_id,
        )
        return 0


async def requeue_interrupted_redis_audio_jobs() -> int:
    global _redis_audio_queue_recovered

    if _redis_audio_queue_recovered:
        return 0

    client = await get_redis_client()
    moved_count = 0

    while True:
        raw_job = await client.rpoplpush(
            REDIS_AUDIO_QUEUE_PROCESSING_KEY,
            READING_AUDIO_QUEUE_REDIS_KEY,
        )

        if raw_job is None:
            break

        moved_count += 1

    _redis_audio_queue_recovered = True

    if moved_count:
        logger.warning(
            "ReadingAudioQueue: requeued interrupted Redis jobs count=%s",
            moved_count,
        )

    return moved_count


async def _ack_redis_audio_job(raw_job: str) -> None:
    client = await get_redis_client()
    await client.lrem(REDIS_AUDIO_QUEUE_PROCESSING_KEY, 1, raw_job)


async def _redis_audio_generation_worker(
    job_handler: SerializedAudioJobHandler,
) -> None:
    bot = Bot(BOT_TOKEN)

    try:
        while True:
            raw_job = None

            try:
                client = await get_redis_client()
                raw_job = await client.brpoplpush(
                    READING_AUDIO_QUEUE_REDIS_KEY,
                    REDIS_AUDIO_QUEUE_PROCESSING_KEY,
                    timeout=REDIS_AUDIO_QUEUE_BLPOP_TIMEOUT_SECONDS,
                )

                if raw_job is None:
                    continue

                job = json.loads(raw_job)

                if not isinstance(job, dict):
                    logger.warning("ReadingAudioQueue: Redis job is not an object")
                    await _ack_redis_audio_job(raw_job)
                    continue

                await job_handler(bot, cast(SerializedAudioJob, job))
                await _ack_redis_audio_job(raw_job)

            except asyncio.CancelledError:
                raise

            except (RedisError, json.JSONDecodeError, KeyError, ValueError):
                logger.exception("ReadingAudioQueue: Redis worker job failed")
                if raw_job is not None:
                    with suppress(RedisError):
                        await _ack_redis_audio_job(raw_job)
                await asyncio.sleep(1)

            except Exception:
                logger.exception("ReadingAudioQueue: Redis audio job failed")
                if raw_job is not None:
                    with suppress(RedisError):
                        await _ack_redis_audio_job(raw_job)

    finally:
        await bot.session.close()


async def start_audio_workers(job_handler: SerializedAudioJobHandler) -> None:
    if not use_redis_audio_queue():
        return

    await requeue_interrupted_redis_audio_jobs()
    _ensure_redis_audio_generation_worker(job_handler)


def _ensure_redis_audio_generation_worker(
    job_handler: SerializedAudioJobHandler,
) -> None:
    global _redis_audio_generation_worker_task

    if (
        _redis_audio_generation_worker_task is None
        or _redis_audio_generation_worker_task.done()
    ):
        _redis_audio_generation_worker_task = asyncio.create_task(
            _redis_audio_generation_worker(job_handler)
        )


async def redis_audio_queue_position() -> int:
    client = await get_redis_client()
    queue_size = await client.llen(READING_AUDIO_QUEUE_REDIS_KEY)
    return int(queue_size) + 1


async def get_audio_queue_stats() -> AudioQueueStats:
    if use_redis_audio_queue():
        try:
            client = await get_redis_client()
            pending = int(await client.llen(READING_AUDIO_QUEUE_REDIS_KEY))
            processing = int(await client.llen(REDIS_AUDIO_QUEUE_PROCESSING_KEY))

            return AudioQueueStats(
                backend="redis",
                max_size=READING_AUDIO_QUEUE_MAX_SIZE,
                pending=pending,
                processing=processing,
                worker_running=_redis_worker_running(),
            )
        except RedisError as error:
            logger.exception("ReadingAudioQueue: failed to read Redis queue stats")
            return AudioQueueStats(
                backend="redis",
                max_size=READING_AUDIO_QUEUE_MAX_SIZE,
                pending=None,
                processing=None,
                worker_running=_redis_worker_running(),
                degraded=True,
                error=error.__class__.__name__,
            )

    queue = _audio_generation_queue

    return AudioQueueStats(
        backend="memory",
        max_size=READING_AUDIO_QUEUE_MAX_SIZE,
        pending=queue.qsize() if queue is not None else 0,
        processing=0,
        worker_running=_memory_worker_running(),
    )


async def enqueue_redis_audio_job(
    job: SerializedAudioJob,
    job_handler: SerializedAudioJobHandler,
) -> None:
    await start_audio_workers(job_handler)
    client = await get_redis_client()

    queue_size = await client.llen(READING_AUDIO_QUEUE_REDIS_KEY)

    if int(queue_size) >= READING_AUDIO_QUEUE_MAX_SIZE:
        raise asyncio.QueueFull

    await client.lpush(READING_AUDIO_QUEUE_REDIS_KEY, serialize_audio_job(job))


def ensure_memory_audio_generation_queue() -> asyncio.Queue[AudioGenerationJob]:
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


async def close_audio_queue(
    timeout_seconds: float = READING_AUDIO_QUEUE_FLUSH_TIMEOUT_SECONDS,
) -> None:
    global _audio_generation_queue
    global _audio_generation_worker_task
    global _redis_audio_generation_worker_task
    global _redis_audio_queue_recovered

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
    _redis_audio_queue_recovered = False
