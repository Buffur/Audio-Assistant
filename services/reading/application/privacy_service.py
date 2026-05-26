import logging
import time

from redis.exceptions import RedisError

from config import READING_SESSION_BACKEND, READING_SESSION_TTL_SECONDS
from services.audio_cache import clear_audio_cache
from services.reading import audio_queue
from services.reading.infrastructure.session_store import (
    cleanup_reading_session,
    get_reading_session_model,
)
from services.redis_client import get_redis_client

logger = logging.getLogger(__name__)

PRIVACY_DELETE_MARKER_PREFIX = "privacy:delete:"
PRIVACY_DELETE_MARKER_TTL_SECONDS = max(READING_SESSION_TTL_SECONDS, 3600)

_privacy_delete_markers: dict[int, float] = {}


def _uses_redis_runtime_state() -> bool:
    return audio_queue.use_redis_audio_queue() or READING_SESSION_BACKEND == "redis"


def _privacy_delete_marker_key(user_id: int) -> str:
    return f"{PRIVACY_DELETE_MARKER_PREFIX}{user_id}"


def _prune_memory_privacy_delete_markers(now: float | None = None) -> None:
    current_time = now or time.time()
    expired_user_ids = [
        user_id
        for user_id, marked_at in _privacy_delete_markers.items()
        if current_time - marked_at > PRIVACY_DELETE_MARKER_TTL_SECONDS
    ]

    for user_id in expired_user_ids:
        _privacy_delete_markers.pop(user_id, None)


async def mark_user_data_deletion(user_id: int) -> None:
    marked_at = time.time()
    _prune_memory_privacy_delete_markers(now=marked_at)
    _privacy_delete_markers[user_id] = marked_at

    if not _uses_redis_runtime_state():
        return

    try:
        client = await get_redis_client()
        await client.setex(
            _privacy_delete_marker_key(user_id),
            PRIVACY_DELETE_MARKER_TTL_SECONDS,
            str(marked_at),
        )
    except RedisError:
        logger.exception(
            "ReadingPrivacyService: failed to write privacy deletion marker user_id=%s",
            user_id,
        )


async def _get_user_data_deletion_timestamp(user_id: int) -> float | None:
    _prune_memory_privacy_delete_markers()
    memory_value = _privacy_delete_markers.get(user_id)

    if not _uses_redis_runtime_state():
        return memory_value

    try:
        client = await get_redis_client()
        raw_value = await client.get(_privacy_delete_marker_key(user_id))
    except RedisError:
        logger.exception(
            "ReadingPrivacyService: failed to read privacy deletion marker user_id=%s",
            user_id,
        )
        return memory_value

    try:
        redis_value = float(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        redis_value = None

    if memory_value is None:
        return redis_value

    if redis_value is None:
        return memory_value

    return max(memory_value, redis_value)


async def should_skip_deleted_user_job(
    user_id: int,
    job_created_at: float | None,
) -> bool:
    deleted_at = await _get_user_data_deletion_timestamp(user_id)

    if deleted_at is None:
        return False

    return job_created_at is None or job_created_at <= deleted_at


async def purge_queued_audio_jobs_for_user(user_id: int) -> int:
    return await audio_queue.purge_queued_audio_jobs_for_user(user_id)


async def cleanup_user_private_runtime_data(user_id: int) -> dict[str, int]:
    await mark_user_data_deletion(user_id)

    session = await get_reading_session_model(user_id)
    await cleanup_reading_session(user_id)
    queued_audio_jobs = await purge_queued_audio_jobs_for_user(user_id)
    audio_cache_result = clear_audio_cache()

    return {
        "reading_session": 1 if session else 0,
        "queued_audio_jobs": queued_audio_jobs,
        "audio_cache_files": audio_cache_result["removed_files"],
    }
