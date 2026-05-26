import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from redis.exceptions import RedisError

from services.reading.infrastructure import session_state as state

logger = logging.getLogger(__name__)

RedisClientFactory = Callable[[], Awaitable[Any]]


class RedisReadingSessionRepository:
    def __init__(self, get_redis_client: RedisClientFactory) -> None:
        self._get_redis_client = get_redis_client

    async def _client(self):
        return await self._get_redis_client()

    async def _get_session(self, user_id: int) -> dict[str, Any] | None:
        client = await self._client()
        raw_session = await client.get(state.session_key(user_id))
        session = state.deserialize_session(raw_session)

        if session is None:
            await client.srem(state.SESSION_USERS_KEY, str(user_id))
            return None

        return session

    async def _store_session(self, user_id: int, session: dict[str, Any]) -> None:
        client = await self._client()
        normalized_session = state.normalized_session_mapping(session)
        await client.setex(
            state.session_key(user_id),
            state.SESSION_TTL_SECONDS,
            state.serialize_session(normalized_session),
        )
        await client.sadd(state.SESSION_USERS_KEY, str(user_id))

    async def set(self, user_id: int, session: dict[str, Any]) -> None:
        try:
            await self._store_session(user_id, session)
        except RedisError as error:
            state.raise_redis_unavailable("set", user_id, error)
        else:
            state._reading_sessions[user_id] = state.sanitize_session_for_redis(
                session
            )

    async def get(self, user_id: int) -> dict[str, Any] | None:
        try:
            session = await self._get_session(user_id)

            if session is None:
                return None

            if state.is_generation_stale(session):
                state.recover_stale_generation(session, user_id)

            state.touch_session(session)
            await self._store_session(user_id, session)
            state._reading_sessions[user_id] = session
            return session
        except RedisError as error:
            state.raise_redis_unavailable("get", user_id, error)

    async def try_start_generation(self, user_id: int) -> bool:
        try:
            client = await self._client()
            result = await client.eval(
                """
                local function remove_empty_optional_lists(session)
                    local fields = {
                        "prefetch_audio_files",
                        "summary_voice_file_ids"
                    }

                    for _, field in ipairs(fields) do
                        local value = session[field]

                        if value == cjson.null then
                            session[field] = nil
                        elseif type(value) == "table" and next(value) == nil then
                            session[field] = nil
                        end
                    end
                end

                local raw_session = redis.call("GET", KEYS[1])
                if not raw_session then
                    redis.call("SREM", KEYS[2], ARGV[1])
                    return 0
                end

                local session = cjson.decode(raw_session)
                if session["is_generating"] then
                    local generation_started_at = tonumber(
                        session["generation_started_at"]
                        or session["updated_at"]
                        or session["created_at"]
                        or ARGV[2]
                    )

                    if tonumber(ARGV[2]) - generation_started_at <= tonumber(ARGV[4]) then
                        return 2
                    end

                    session["is_generating"] = false
                    session["generation_recovered_at"] = tonumber(ARGV[2])
                end

                session["is_generating"] = true
                session["updated_at"] = tonumber(ARGV[2])
                session["generation_started_at"] = tonumber(ARGV[2])
                remove_empty_optional_lists(session)
                redis.call("SETEX", KEYS[1], tonumber(ARGV[3]), cjson.encode(session))
                redis.call("SADD", KEYS[2], ARGV[1])
                return 1
                """,
                2,
                state.session_key(user_id),
                state.SESSION_USERS_KEY,
                str(user_id),
                str(state.now()),
                str(state.SESSION_TTL_SECONDS),
                str(state.GENERATION_STALE_SECONDS),
            )

            if int(result) == 1:
                return True

            if int(result) == 2:
                return False

            return False
        except RedisError as error:
            state.raise_redis_unavailable("try_start", user_id, error)

    async def update(self, user_id: int, **fields: Any) -> None:
        safe_fields = state.sanitize_session_for_redis(
            state.updates_with_generation_metadata(fields)
        )

        try:
            client = await self._client()
            result = await client.eval(
                """
                local function remove_empty_optional_lists(session)
                    local fields = {
                        "prefetch_audio_files",
                        "summary_voice_file_ids"
                    }

                    for _, field in ipairs(fields) do
                        local value = session[field]

                        if value == cjson.null then
                            session[field] = nil
                        elseif type(value) == "table" and next(value) == nil then
                            session[field] = nil
                        end
                    end
                end

                local raw_session = redis.call("GET", KEYS[1])
                if not raw_session then
                    redis.call("SREM", KEYS[2], ARGV[1])
                    return 0
                end

                local session = cjson.decode(raw_session)
                local updates = cjson.decode(ARGV[2])

                for key, value in pairs(updates) do
                    session[key] = value
                end

                remove_empty_optional_lists(session)
                redis.call("SETEX", KEYS[1], tonumber(ARGV[3]), cjson.encode(session))
                redis.call("SADD", KEYS[2], ARGV[1])
                return 1
                """,
                2,
                state.session_key(user_id),
                state.SESSION_USERS_KEY,
                str(user_id),
                json.dumps(safe_fields, ensure_ascii=False),
                str(state.SESSION_TTL_SECONDS),
            )

            if result:
                local_session = state._reading_sessions.setdefault(user_id, {})
                local_session.update(safe_fields)
        except RedisError as error:
            state.raise_redis_unavailable("update", user_id, error)

    async def cleanup(self, user_id: int) -> None:
        session: dict[str, Any] | None = None

        try:
            session = await self._get_session(user_id)
            client = await self._client()
            await client.delete(state.session_key(user_id))
            await client.srem(state.SESSION_USERS_KEY, str(user_id))
        except RedisError as error:
            state.raise_redis_unavailable("cleanup", user_id, error)

        lock = await state.get_user_session_lock(user_id)

        async with lock:
            local_session = state._reading_sessions.pop(user_id, None)

        session = session or local_session

        if not session:
            return

        await state.cleanup_session_artifacts(session)

        logger.info(
            "ReadingSessionStore: cleaned session user_id=%s session_id=%s",
            user_id,
            session.get("session_id"),
        )

    async def cleanup_expired(self) -> int:
        try:
            client = await self._client()
            user_ids = await client.smembers(state.SESSION_USERS_KEY)
            stale_user_ids: list[str] = []

            for raw_user_id in user_ids:
                if not await client.exists(state.session_key(int(raw_user_id))):
                    stale_user_ids.append(str(raw_user_id))

            if stale_user_ids:
                await client.srem(state.SESSION_USERS_KEY, *stale_user_ids)

            return len(stale_user_ids)
        except RedisError as error:
            state.raise_redis_unavailable("expired_cleanup", 0, error)
        except ValueError:
            logger.exception("ReadingSessionStore: invalid Redis session user id")
            return 0

    async def cleanup_all(self) -> None:
        await state.clear_user_locks()
        state._reading_sessions.clear()
        logger.info(
            "ReadingSessionStore: local state cleaned; Redis sessions left to TTL"
        )
