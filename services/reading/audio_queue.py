import asyncio
import json
import logging
import time
import uuid
from collections import deque
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
    READING_AUDIO_QUEUE_WORKER_COUNT,
)
from services.redis_client import get_redis_client

logger = logging.getLogger(__name__)

READING_AUDIO_QUEUE_FLUSH_TIMEOUT_SECONDS = 10.0
REDIS_AUDIO_QUEUE_BLPOP_TIMEOUT_SECONDS = 5
REDIS_AUDIO_QUEUE_PROCESSING_KEY = f"{READING_AUDIO_QUEUE_REDIS_KEY}:processing"
REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY = f"{READING_AUDIO_QUEUE_REDIS_KEY}:prefetch"
REDIS_PREFETCH_AUDIO_QUEUE_PROCESSING_KEY = (
    f"{REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY}:processing"
)
DEFERRED_AUDIO_JOB_SLEEP_SECONDS = 0.05
REDIS_PREFETCH_QUEUE_POP_TIMEOUT_SECONDS = 1

AudioGenerationJob = Callable[[], Awaitable[None]]
AudioJobType = Literal["send_chunk", "export_audio", "prefetch_chunk"]
AudioQueuePriority = Literal["user_visible", "prefetch"]
USER_VISIBLE_AUDIO_JOB_TYPES: set[str] = {"send_chunk", "export_audio"}


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


class InvalidAudioJobError(ValueError):
    """Raised when a queued audio job does not match the runtime payload schema."""


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
    def active(self) -> int | None:
        if self.pending is None or self.processing is None:
            return None

        return self.pending + self.processing

    @property
    def is_full(self) -> bool | None:
        if self.active is None:
            return None

        return self.active >= self.max_size

    @property
    def available_capacity(self) -> int | None:
        if self.active is None:
            return None

        return max(self.max_size - self.active, 0)

    def as_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "max_size": self.max_size,
            "pending": self.pending,
            "processing": self.processing,
            "active": self.active,
            "worker_running": self.worker_running,
            "degraded": self.degraded,
            "error": self.error,
            "is_full": self.is_full,
            "available_capacity": self.available_capacity,
        }

_audio_generation_queue: asyncio.Queue[AudioGenerationJob] | None = None
_prefetch_audio_generation_queue: asyncio.Queue[AudioGenerationJob] | None = None
_memory_audio_generation_enqueue_event: asyncio.Event | None = None
_audio_generation_worker_tasks: set[asyncio.Task] = set()
_memory_audio_generation_pending_user_visible = 0
_memory_audio_generation_processing = 0
_memory_audio_generation_processing_user_visible = 0
_memory_audio_generation_deferred_jobs: dict[
    int,
    deque[tuple[AudioGenerationJob, AudioQueuePriority]],
] = {}
_redis_audio_generation_worker_tasks: set[asyncio.Task] = set()
_redis_audio_generation_stop_event: asyncio.Event | None = None
_redis_audio_generation_active_raw_jobs: dict[str, str] = {}
_redis_audio_generation_deferred_jobs: dict[
    int,
    deque[tuple[str, SerializedAudioJob, AudioQueuePriority]],
] = {}
_redis_audio_queue_recovered = False
_active_audio_user_ids: set[int] = set()
_active_audio_user_lock: asyncio.Lock | None = None


def _worker_count() -> int:
    return max(int(READING_AUDIO_QUEUE_WORKER_COUNT), 1)


def _memory_audio_job_user_id(job: AudioGenerationJob) -> int | None:
    user_id = getattr(job, "_reading_audio_user_id", None)

    return user_id if isinstance(user_id, int) else None


def _memory_audio_job_type(job: AudioGenerationJob) -> str | None:
    job_type = getattr(job, "_reading_audio_job_type", None)

    return job_type if isinstance(job_type, str) else None


def _is_user_visible_audio_job_type(job_type: object) -> bool:
    return isinstance(job_type, str) and job_type in USER_VISIBLE_AUDIO_JOB_TYPES


def _memory_audio_job_is_user_visible(job: AudioGenerationJob) -> bool:
    job_type = _memory_audio_job_type(job)

    if job_type is None:
        return True

    return _is_user_visible_audio_job_type(job_type)


def _audio_job_priority_from_type(job_type: object) -> AudioQueuePriority:
    return (
        "user_visible"
        if _is_user_visible_audio_job_type(job_type)
        else "prefetch"
    )


def _memory_audio_job_priority(job: AudioGenerationJob) -> AudioQueuePriority:
    job_type = _memory_audio_job_type(job)

    if job_type is None:
        return "user_visible"

    return _audio_job_priority_from_type(job_type)


def _serialized_audio_job_priority(job: SerializedAudioJob) -> AudioQueuePriority:
    return _audio_job_priority_from_type(job.get("type"))


def _redis_pending_key_for_priority(priority: AudioQueuePriority) -> str:
    return (
        READING_AUDIO_QUEUE_REDIS_KEY
        if priority == "user_visible"
        else REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY
    )


def _redis_processing_key_for_priority(priority: AudioQueuePriority) -> str:
    return (
        REDIS_AUDIO_QUEUE_PROCESSING_KEY
        if priority == "user_visible"
        else REDIS_PREFETCH_AUDIO_QUEUE_PROCESSING_KEY
    )


def _redis_pending_key_for_processing_key(processing_key: str) -> str:
    return (
        REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY
        if processing_key == REDIS_PREFETCH_AUDIO_QUEUE_PROCESSING_KEY
        else READING_AUDIO_QUEUE_REDIS_KEY
    )


def set_audio_generation_job_user_id(
    job: AudioGenerationJob,
    user_id: int,
) -> AudioGenerationJob:
    setattr(job, "_reading_audio_user_id", user_id)
    return job


def set_audio_generation_job_type(
    job: AudioGenerationJob,
    job_type: AudioJobType,
) -> AudioGenerationJob:
    setattr(job, "_reading_audio_job_type", job_type)
    return job


def set_audio_generation_job_metadata(
    job: AudioGenerationJob,
    *,
    user_id: int,
    job_type: AudioJobType,
) -> AudioGenerationJob:
    set_audio_generation_job_user_id(job, user_id)
    set_audio_generation_job_type(job, job_type)
    return job


def _active_user_lock() -> asyncio.Lock:
    global _active_audio_user_lock

    if _active_audio_user_lock is None:
        _active_audio_user_lock = asyncio.Lock()

    return _active_audio_user_lock


def _memory_audio_queue_event() -> asyncio.Event:
    global _memory_audio_generation_enqueue_event

    if _memory_audio_generation_enqueue_event is None:
        _memory_audio_generation_enqueue_event = asyncio.Event()

    return _memory_audio_generation_enqueue_event


async def _try_reserve_audio_user(user_id: int | None) -> bool:
    if user_id is None:
        return True

    async with _active_user_lock():
        if user_id in _active_audio_user_ids:
            return False

        _active_audio_user_ids.add(user_id)
        return True


async def _release_audio_user(user_id: int | None) -> None:
    if user_id is None:
        return

    async with _active_user_lock():
        _active_audio_user_ids.discard(user_id)


def _deferred_memory_jobs_count() -> int:
    return sum(len(jobs) for jobs in _memory_audio_generation_deferred_jobs.values())


def _deferred_memory_user_visible_jobs_count() -> int:
    return sum(
        1
        for jobs in _memory_audio_generation_deferred_jobs.values()
        for job, priority in jobs
        if _memory_audio_job_is_user_visible(job)
        and priority == "user_visible"
    )


def _defer_memory_audio_job(
    user_id: int,
    job: AudioGenerationJob,
    priority: AudioQueuePriority,
) -> None:
    _memory_audio_generation_deferred_jobs.setdefault(user_id, deque()).append(
        (job, priority)
    )


async def _pop_ready_deferred_memory_audio_job(
    priority: AudioQueuePriority,
) -> tuple[AudioGenerationJob, AudioQueuePriority] | None:
    for user_id, jobs in list(_memory_audio_generation_deferred_jobs.items()):
        if not jobs:
            _memory_audio_generation_deferred_jobs.pop(user_id, None)
            continue

        ready_index = next(
            (
                index
                for index, (_job, job_priority) in enumerate(jobs)
                if job_priority == priority
            ),
            None,
        )

        if ready_index is None:
            continue

        if not await _try_reserve_audio_user(user_id):
            continue

        job, job_priority = jobs[ready_index]
        del jobs[ready_index]

        if not jobs:
            _memory_audio_generation_deferred_jobs.pop(user_id, None)

        return job, job_priority

    return None


def _deferred_redis_jobs_count() -> int:
    return sum(len(jobs) for jobs in _redis_audio_generation_deferred_jobs.values())


def _defer_redis_audio_job(
    raw_job: str,
    job: SerializedAudioJob,
    priority: AudioQueuePriority,
) -> None:
    user_id = int(job["user_id"])
    _redis_audio_generation_deferred_jobs.setdefault(user_id, deque()).append(
        (raw_job, job, priority)
    )


async def _pop_ready_deferred_redis_audio_job(
    priority: AudioQueuePriority,
) -> tuple[str, SerializedAudioJob, AudioQueuePriority] | None:
    for user_id, jobs in list(_redis_audio_generation_deferred_jobs.items()):
        if not jobs:
            _redis_audio_generation_deferred_jobs.pop(user_id, None)
            continue

        ready_index = next(
            (
                index
                for index, (_raw_job, _job, job_priority) in enumerate(jobs)
                if job_priority == priority
            ),
            None,
        )

        if ready_index is None:
            continue

        if not await _try_reserve_audio_user(user_id):
            continue

        raw_job, job, job_priority = jobs[ready_index]
        del jobs[ready_index]

        if not jobs:
            _redis_audio_generation_deferred_jobs.pop(user_id, None)

        return raw_job, job, job_priority

    return None


async def _audio_generation_worker(
    queue: asyncio.Queue[AudioGenerationJob],
) -> None:
    global _memory_audio_generation_processing
    global _memory_audio_generation_pending_user_visible
    global _memory_audio_generation_processing_user_visible

    while True:
        job_result = await _pop_next_memory_audio_job(queue)

        if job_result is None:
            await _memory_audio_queue_event().wait()
            _memory_audio_queue_event().clear()
            continue

        job, priority = job_result
        user_id = _memory_audio_job_user_id(job)
        is_user_visible_job = priority == "user_visible"
        _memory_audio_generation_processing += 1
        if is_user_visible_job:
            _memory_audio_generation_processing_user_visible += 1

        try:
            await job()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ReadingAudioQueue: background audio job failed")
        finally:
            _memory_audio_generation_processing = max(
                _memory_audio_generation_processing - 1,
                0,
            )
            if is_user_visible_job:
                _memory_audio_generation_processing_user_visible = max(
                    _memory_audio_generation_processing_user_visible - 1,
                    0,
                )
            await _release_audio_user(user_id)
            if priority == "prefetch" and _prefetch_audio_generation_queue is not None:
                _prefetch_audio_generation_queue.task_done()
            else:
                queue.task_done()


async def _pop_next_memory_audio_job(
    queue: asyncio.Queue[AudioGenerationJob],
) -> tuple[AudioGenerationJob, AudioQueuePriority] | None:
    prefetch_queue = _prefetch_audio_generation_queue

    for priority in ("user_visible", "prefetch"):
        deferred_job = await _pop_ready_deferred_memory_audio_job(priority)

        if deferred_job is not None:
            return deferred_job

        source_queue = queue if priority == "user_visible" else prefetch_queue

        if source_queue is None:
            continue

        while True:
            try:
                job = source_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if priority == "user_visible":
                global _memory_audio_generation_pending_user_visible
                _memory_audio_generation_pending_user_visible = max(
                    _memory_audio_generation_pending_user_visible - 1,
                    0,
                )

            user_id = _memory_audio_job_user_id(job)

            if not await _try_reserve_audio_user(user_id):
                if user_id is not None:
                    _defer_memory_audio_job(user_id, job, priority)
                    await asyncio.sleep(DEFERRED_AUDIO_JOB_SLEEP_SECONDS)
                    continue

            return job, priority

    return None


def use_redis_audio_queue() -> bool:
    return READING_AUDIO_QUEUE_BACKEND == "redis"


def _memory_worker_running() -> bool:
    return any(not task.done() for task in _audio_generation_worker_tasks)


def _redis_worker_running() -> bool:
    return any(not task.done() for task in _redis_audio_generation_worker_tasks)


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


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_int(job: dict[str, object], key: str) -> None:
    if not _is_int(job.get(key)):
        raise InvalidAudioJobError(f"{key} must be an integer")


def _require_str(job: dict[str, object], key: str) -> None:
    if not isinstance(job.get(key), str):
        raise InvalidAudioJobError(f"{key} must be a string")


def _require_optional_int(job: dict[str, object], key: str) -> None:
    if key not in job:
        raise InvalidAudioJobError(f"{key} is required")

    value = job[key]

    if value is not None and not _is_int(value):
        raise InvalidAudioJobError(f"{key} must be an integer or null")


def _require_provider_chain(job: dict[str, object]) -> None:
    provider_chain = job.get("provider_chain")

    if not isinstance(provider_chain, list) or not all(
        isinstance(provider, str) for provider in provider_chain
    ):
        raise InvalidAudioJobError("provider_chain must be a list of strings")


def _validate_optional_metadata(job: dict[str, object]) -> None:
    if "created_at" in job and not _is_number(job["created_at"]):
        raise InvalidAudioJobError("created_at must be a number")

    if "job_id" in job and not isinstance(job["job_id"], str):
        raise InvalidAudioJobError("job_id must be a string")


def validate_audio_job(raw_job: object) -> SerializedAudioJob:
    if not isinstance(raw_job, dict):
        raise InvalidAudioJobError("audio job must be an object")

    job = cast(dict[str, object], raw_job)
    job_type = job.get("type")

    if job_type == "send_chunk":
        _require_int(job, "user_id")
        _require_int(job, "chat_id")
        _require_str(job, "session_id")
        _require_optional_int(job, "status_message_id")
    elif job_type == "export_audio":
        _require_int(job, "user_id")
        _require_int(job, "chat_id")
        _require_str(job, "session_id")
        _require_optional_int(job, "status_message_id")
    elif job_type == "prefetch_chunk":
        _require_int(job, "user_id")
        _require_str(job, "session_id")
        _require_int(job, "chunk_index")
        _require_str(job, "chunk_text")
        _require_str(job, "voice")
        _require_str(job, "rate")
        _require_provider_chain(job)
    else:
        raise InvalidAudioJobError("unsupported audio job type")

    _validate_optional_metadata(job)

    return cast(SerializedAudioJob, job)


def serialize_audio_job(job: SerializedAudioJob) -> str:
    payload = dict(validate_audio_job(job))
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
            4,
            READING_AUDIO_QUEUE_REDIS_KEY,
            REDIS_AUDIO_QUEUE_PROCESSING_KEY,
            REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY,
            REDIS_PREFETCH_AUDIO_QUEUE_PROCESSING_KEY,
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

    for processing_key, pending_key in (
        (REDIS_AUDIO_QUEUE_PROCESSING_KEY, READING_AUDIO_QUEUE_REDIS_KEY),
        (
            REDIS_PREFETCH_AUDIO_QUEUE_PROCESSING_KEY,
            REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY,
        ),
    ):
        while True:
            raw_job = await client.rpoplpush(
                processing_key,
                pending_key,
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


async def _ack_redis_audio_job(raw_job: str, processing_key: str) -> None:
    client = await get_redis_client()
    await client.lrem(processing_key, 1, raw_job)


async def _requeue_redis_audio_job(
    raw_job: str,
    *,
    processing_key: str,
    pending_key: str,
) -> int:
    client = await get_redis_client()
    moved_count = await client.eval(
        """
        local removed = redis.call("LREM", KEYS[1], 1, ARGV[1])

        if removed > 0 then
            redis.call("LPUSH", KEYS[2], ARGV[1])
        end

        return removed
        """,
        2,
        processing_key,
        pending_key,
        raw_job,
    )

    return int(moved_count or 0)


def _set_active_redis_audio_job(raw_job: str, processing_key: str) -> None:
    _redis_audio_generation_active_raw_jobs[raw_job] = processing_key


def _clear_active_redis_audio_job(raw_job: str) -> None:
    _redis_audio_generation_active_raw_jobs.pop(raw_job, None)


async def _requeue_active_redis_audio_job() -> int:
    raw_jobs = list(_redis_audio_generation_active_raw_jobs.items())

    if not raw_jobs:
        return 0

    requeued_count = 0

    try:
        for raw_job, processing_key in raw_jobs:
            pending_key = _redis_pending_key_for_processing_key(processing_key)
            moved_count = await _requeue_redis_audio_job(
                raw_job,
                processing_key=processing_key,
                pending_key=pending_key,
            )
            requeued_count += moved_count

            if not moved_count:
                logger.warning(
                    "ReadingAudioQueue: active Redis job was not found in "
                    "processing during shutdown",
                )

        if requeued_count:
            logger.warning(
                "ReadingAudioQueue: requeued active/deferred Redis jobs during "
                "shutdown count=%s",
                requeued_count,
            )

        return requeued_count

    except RedisError:
        logger.exception(
            "ReadingAudioQueue: failed to requeue active/deferred Redis jobs "
            "during shutdown",
        )
        return requeued_count

    finally:
        _redis_audio_generation_active_raw_jobs.clear()
        _redis_audio_generation_deferred_jobs.clear()


async def _pop_redis_audio_job_from_queue(
    client,
    priority: AudioQueuePriority,
    *,
    timeout: int,
) -> tuple[str, SerializedAudioJob, AudioQueuePriority, str, bool] | None:
    pending_key = _redis_pending_key_for_priority(priority)
    processing_key = _redis_processing_key_for_priority(priority)

    raw_job = await client.brpoplpush(
        pending_key,
        processing_key,
        timeout=timeout,
    )

    if raw_job is None:
        return None

    _set_active_redis_audio_job(raw_job, processing_key)

    try:
        job = validate_audio_job(json.loads(raw_job))
    except InvalidAudioJobError as error:
        logger.warning(
            "ReadingAudioQueue: invalid Redis job skipped: %s",
            error,
        )
        await _ack_redis_audio_job(raw_job, processing_key)
        _clear_active_redis_audio_job(raw_job)
        return None

    return raw_job, job, priority, processing_key, False


async def _pop_next_redis_audio_job(
    client,
) -> tuple[str, SerializedAudioJob, AudioQueuePriority, str, bool] | None:
    deferred_user_visible = await _pop_ready_deferred_redis_audio_job("user_visible")

    if deferred_user_visible is not None:
        raw_job, job, job_priority = deferred_user_visible
        processing_key = _redis_processing_key_for_priority(job_priority)
        return raw_job, job, job_priority, processing_key, True

    user_visible_job = await _pop_redis_audio_job_from_queue(
        client,
        "user_visible",
        timeout=REDIS_PREFETCH_QUEUE_POP_TIMEOUT_SECONDS,
    )

    if user_visible_job is not None:
        return user_visible_job

    deferred_prefetch = await _pop_ready_deferred_redis_audio_job("prefetch")

    if deferred_prefetch is not None:
        raw_job, job, priority = deferred_prefetch
        return (
            raw_job,
            job,
            priority,
            _redis_processing_key_for_priority(priority),
            True,
        )

    return await _pop_redis_audio_job_from_queue(
        client,
        "prefetch",
        timeout=REDIS_PREFETCH_QUEUE_POP_TIMEOUT_SECONDS,
    )


async def _redis_audio_generation_worker(
    job_handler: SerializedAudioJobHandler,
    stop_event: asyncio.Event,
) -> None:
    bot = Bot(BOT_TOKEN)

    try:
        while not stop_event.is_set():
            raw_job = None
            reserved_user_id: int | None = None
            processing_key: str | None = None

            try:
                client = await get_redis_client()
                next_job = await _pop_next_redis_audio_job(client)

                if next_job is None:
                    continue

                raw_job, job, priority, processing_key, user_already_reserved = next_job

                if stop_event.is_set():
                    try:
                        await _requeue_redis_audio_job(
                            raw_job,
                            processing_key=processing_key,
                            pending_key=_redis_pending_key_for_priority(priority),
                        )
                        _clear_active_redis_audio_job(raw_job)
                    except RedisError:
                        logger.exception(
                            "ReadingAudioQueue: failed to requeue Redis job "
                            "after shutdown signal",
                        )
                    break

                user_id = int(job["user_id"])

                if user_already_reserved:
                    reserved_user_id = user_id
                else:
                    if not await _try_reserve_audio_user(user_id):
                        _defer_redis_audio_job(raw_job, job, priority)
                        await asyncio.sleep(DEFERRED_AUDIO_JOB_SLEEP_SECONDS)
                        continue

                    reserved_user_id = user_id

                await job_handler(bot, job)
                await _ack_redis_audio_job(raw_job, processing_key)
                _clear_active_redis_audio_job(raw_job)
                await _release_audio_user(reserved_user_id)
                reserved_user_id = None

            except asyncio.CancelledError:
                await _release_audio_user(reserved_user_id)
                raise

            except (RedisError, json.JSONDecodeError, KeyError, ValueError):
                logger.exception("ReadingAudioQueue: Redis worker job failed")
                if raw_job is not None and processing_key is not None:
                    with suppress(RedisError):
                        await _ack_redis_audio_job(raw_job, processing_key)
                    _clear_active_redis_audio_job(raw_job)
                await _release_audio_user(reserved_user_id)
                await asyncio.sleep(1)

            except Exception:
                logger.exception("ReadingAudioQueue: Redis audio job failed")
                if raw_job is not None and processing_key is not None:
                    with suppress(RedisError):
                        await _ack_redis_audio_job(raw_job, processing_key)
                    _clear_active_redis_audio_job(raw_job)
                await _release_audio_user(reserved_user_id)

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
    global _redis_audio_generation_stop_event

    for task in list(_redis_audio_generation_worker_tasks):
        if task.done():
            _redis_audio_generation_worker_tasks.discard(task)

    if _redis_audio_generation_stop_event is None:
        _redis_audio_generation_stop_event = asyncio.Event()

    while len(_redis_audio_generation_worker_tasks) < _worker_count():
        worker_task = asyncio.create_task(
            _redis_audio_generation_worker(
                job_handler,
                _redis_audio_generation_stop_event,
            )
        )
        _redis_audio_generation_worker_tasks.add(worker_task)


async def redis_audio_queue_position() -> int:
    client = await get_redis_client()
    user_visible_jobs = await _redis_audio_queue_user_visible_load(client)
    return user_visible_jobs + 1


async def _redis_audio_queue_load(client) -> tuple[int, int]:
    pending = int(await client.llen(READING_AUDIO_QUEUE_REDIS_KEY)) + int(
        await client.llen(REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY)
    )
    processing = int(await client.llen(REDIS_AUDIO_QUEUE_PROCESSING_KEY)) + int(
        await client.llen(REDIS_PREFETCH_AUDIO_QUEUE_PROCESSING_KEY)
    )
    return pending, processing


async def _redis_audio_queue_user_visible_load(client) -> int:
    count = await client.eval(
        """
        local visible = 0

        for key_index = 1, #KEYS do
            local key = KEYS[key_index]
            local items = redis.call("LRANGE", key, 0, -1)

            for _, item in ipairs(items) do
                local ok, job = pcall(cjson.decode, item)

                if ok then
                    local job_type = tostring(job["type"])

                    if job_type == "send_chunk" or job_type == "export_audio" then
                        visible = visible + 1
                    end
                end
            end
        end

        return visible
        """,
        2,
        READING_AUDIO_QUEUE_REDIS_KEY,
        REDIS_AUDIO_QUEUE_PROCESSING_KEY,
    )

    return int(count or 0)


async def get_audio_queue_stats() -> AudioQueueStats:
    if use_redis_audio_queue():
        try:
            client = await get_redis_client()
            pending, processing = await _redis_audio_queue_load(client)

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
    prefetch_queue = _prefetch_audio_generation_queue

    return AudioQueueStats(
        backend="memory",
        max_size=READING_AUDIO_QUEUE_MAX_SIZE,
        pending=(
            (queue.qsize() if queue is not None else 0)
            + (prefetch_queue.qsize() if prefetch_queue is not None else 0)
            + _deferred_memory_jobs_count()
        ),
        processing=_memory_audio_generation_processing,
        worker_running=_memory_worker_running(),
    )


async def enqueue_redis_audio_job(
    job: SerializedAudioJob,
    job_handler: SerializedAudioJobHandler,
) -> None:
    validated_job = validate_audio_job(job)
    payload = serialize_audio_job(validated_job)
    priority = _serialized_audio_job_priority(validated_job)
    pending_key = _redis_pending_key_for_priority(priority)

    await start_audio_workers(job_handler)
    client = await get_redis_client()
    accepted = await client.eval(
        """
        local pending = redis.call("LLEN", KEYS[1]) + redis.call("LLEN", KEYS[3])
        local processing = redis.call("LLEN", KEYS[2]) + redis.call("LLEN", KEYS[4])
        local max_size = tonumber(ARGV[1])

        if pending + processing >= max_size then
            return 0
        end

        redis.call("LPUSH", KEYS[5], ARGV[2])
        return 1
        """,
        5,
        READING_AUDIO_QUEUE_REDIS_KEY,
        REDIS_AUDIO_QUEUE_PROCESSING_KEY,
        REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY,
        REDIS_PREFETCH_AUDIO_QUEUE_PROCESSING_KEY,
        pending_key,
        str(READING_AUDIO_QUEUE_MAX_SIZE),
        payload,
    )

    if int(accepted or 0) != 1:
        raise asyncio.QueueFull


def ensure_memory_audio_generation_queue() -> asyncio.Queue[AudioGenerationJob]:
    global _audio_generation_queue
    global _prefetch_audio_generation_queue

    if _audio_generation_queue is None:
        _audio_generation_queue = asyncio.Queue(
            maxsize=READING_AUDIO_QUEUE_MAX_SIZE,
        )

    if _prefetch_audio_generation_queue is None:
        _prefetch_audio_generation_queue = asyncio.Queue(
            maxsize=READING_AUDIO_QUEUE_MAX_SIZE,
        )

    for task in list(_audio_generation_worker_tasks):
        if task.done():
            _audio_generation_worker_tasks.discard(task)

    while len(_audio_generation_worker_tasks) < _worker_count():
        worker_task = asyncio.create_task(
            _audio_generation_worker(_audio_generation_queue)
        )
        _audio_generation_worker_tasks.add(worker_task)

    return _audio_generation_queue


def memory_audio_queue_position() -> int:
    ensure_memory_audio_generation_queue()
    return (
        _memory_audio_generation_pending_user_visible
        + _deferred_memory_user_visible_jobs_count()
        + _memory_audio_generation_processing_user_visible
        + 1
    )


def enqueue_memory_audio_job(job: AudioGenerationJob) -> None:
    global _memory_audio_generation_pending_user_visible

    queue = ensure_memory_audio_generation_queue()
    prefetch_queue = _prefetch_audio_generation_queue
    priority = _memory_audio_job_priority(job)

    active_jobs = (
        queue.qsize()
        + (prefetch_queue.qsize() if prefetch_queue is not None else 0)
        + _deferred_memory_jobs_count()
        + _memory_audio_generation_processing
    )

    if active_jobs >= READING_AUDIO_QUEUE_MAX_SIZE:
        raise asyncio.QueueFull

    target_queue = queue if priority == "user_visible" else prefetch_queue

    if target_queue is None:
        raise RuntimeError("Memory audio prefetch queue is not initialized")

    target_queue.put_nowait(job)
    _memory_audio_queue_event().set()

    if priority == "user_visible":
        _memory_audio_generation_pending_user_visible += 1


async def close_audio_queue(
    timeout_seconds: float = READING_AUDIO_QUEUE_FLUSH_TIMEOUT_SECONDS,
) -> None:
    global _audio_generation_queue
    global _prefetch_audio_generation_queue
    global _memory_audio_generation_enqueue_event
    global _memory_audio_generation_pending_user_visible
    global _memory_audio_generation_processing
    global _memory_audio_generation_processing_user_visible
    global _redis_audio_generation_stop_event
    global _redis_audio_queue_recovered

    current_loop = asyncio.get_running_loop()
    queue = _audio_generation_queue
    prefetch_queue = _prefetch_audio_generation_queue
    worker_tasks = [
        task
        for task in _audio_generation_worker_tasks
        if task.get_loop() is current_loop
    ]
    redis_worker_tasks = [
        task
        for task in _redis_audio_generation_worker_tasks
        if task.get_loop() is current_loop
    ]
    redis_stop_event = _redis_audio_generation_stop_event

    if queue is not None:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(queue.join(), timeout=timeout_seconds)

    if prefetch_queue is not None:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(prefetch_queue.join(), timeout=timeout_seconds)

    for worker_task in worker_tasks:
        if not worker_task.done():
            worker_task.cancel()

    for worker_task in worker_tasks:
        with suppress(asyncio.CancelledError):
            await worker_task

    _audio_generation_queue = None
    _prefetch_audio_generation_queue = None
    _audio_generation_worker_tasks.clear()
    _memory_audio_generation_enqueue_event = None
    _memory_audio_generation_pending_user_visible = 0
    _memory_audio_generation_processing = 0
    _memory_audio_generation_processing_user_visible = 0
    _memory_audio_generation_deferred_jobs.clear()

    if redis_worker_tasks:
        if any(not task.done() for task in redis_worker_tasks):
            if redis_stop_event is not None:
                redis_stop_event.set()

            try:
                await asyncio.wait_for(
                    asyncio.gather(*redis_worker_tasks, return_exceptions=True),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "ReadingAudioQueue: Redis workers shutdown timed out; "
                    "cancelling worker",
                )

                for redis_worker_task in redis_worker_tasks:
                    if not redis_worker_task.done():
                        redis_worker_task.cancel()

                await asyncio.gather(
                    *redis_worker_tasks,
                    return_exceptions=True,
                )

        await _requeue_active_redis_audio_job()

    _redis_audio_generation_worker_tasks.clear()
    _redis_audio_generation_stop_event = None
    _redis_audio_queue_recovered = False
    _active_audio_user_ids.clear()
