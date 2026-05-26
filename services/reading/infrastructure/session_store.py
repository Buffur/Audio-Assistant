import logging
from typing import Any

from config import READING_SESSION_BACKEND
from services.reading.domain.models import InvalidReadingSessionError, ReadingSession
from services.reading.infrastructure.memory_session_repository import (
    MemoryReadingSessionRepository,
)
from services.reading.infrastructure.redis_session_repository import (
    RedisReadingSessionRepository,
)
from services.reading.infrastructure.session_repository import (
    ReadingSessionRepository,
)
from services.reading.infrastructure.session_state import (
    GENERATION_STALE_SECONDS,
    SESSION_KEY_PREFIX,
    SESSION_TTL_SECONDS,
    SESSION_USERS_KEY,
    ReadingSessionStoreUnavailableError,
    _reading_sessions,
    cleanup_session_artifacts,
    deserialize_session,
    get_user_session_lock,
    prepare_session_defaults,
    sanitize_session_for_redis,
    serialize_session,
)
from services.redis_client import get_redis_client

logger = logging.getLogger(__name__)

_memory_repository = MemoryReadingSessionRepository()


def _use_redis_backend() -> bool:
    return READING_SESSION_BACKEND == "redis"


def _repository() -> ReadingSessionRepository:
    if _use_redis_backend():
        return RedisReadingSessionRepository(get_redis_client)

    return _memory_repository


async def set_reading_session(user_id: int, session: dict[str, Any]) -> None:
    """
    Creates or replaces a reading session.

    Redis backend stores JSON-safe state only; live asyncio tasks are only kept for
    the memory backend.
    """
    prepare_session_defaults(session)
    await cleanup_reading_session(user_id)
    await _repository().set(user_id, session)

    logger.info(
        "ReadingSessionStore: created session user_id=%s session_id=%s chunks=%s",
        user_id,
        session.get("session_id"),
        len(session.get("chunks") or []),
    )


async def get_reading_session(user_id: int) -> dict[str, Any] | None:
    return await _repository().get(user_id)


async def get_reading_session_model(user_id: int) -> ReadingSession | None:
    session = await get_reading_session(user_id)

    if session is None:
        return None

    return ReadingSession.from_mapping(session)


async def has_reading_session(user_id: int) -> bool:
    return await get_reading_session(user_id) is not None


async def set_reading_session_generating(user_id: int, is_generating: bool) -> None:
    await update_reading_session(user_id, is_generating=is_generating)


async def try_start_generation(user_id: int) -> bool:
    return await _repository().try_start_generation(user_id)


async def finish_generation(user_id: int) -> None:
    await set_reading_session_generating(user_id, False)


async def update_reading_session(user_id: int, **fields: Any) -> None:
    await _repository().update(user_id, **fields)


async def cleanup_reading_session(user_id: int) -> None:
    await _repository().cleanup(user_id)


async def cleanup_expired_reading_sessions() -> int:
    return await _repository().cleanup_expired()


async def cleanup_all_reading_sessions() -> None:
    await _repository().cleanup_all()
