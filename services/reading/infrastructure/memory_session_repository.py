import asyncio
import logging
from typing import Any

from services.reading.infrastructure import session_state as state

logger = logging.getLogger(__name__)


class MemoryReadingSessionRepository:
    async def set(self, user_id: int, session: dict[str, Any]) -> None:
        lock = await state.get_user_session_lock(user_id)

        async with lock:
            state._reading_sessions[user_id] = session

    async def get(self, user_id: int) -> dict[str, Any] | None:
        task_to_cleanup: asyncio.Task | None = None
        lock = await state.get_user_session_lock(user_id)

        async with lock:
            session = state._reading_sessions.get(user_id)

            if not session:
                return None

            if state.is_expired(session):
                logger.info(
                    "ReadingSessionStore: session expired user_id=%s, cleaning up",
                    user_id,
                )
                task_to_cleanup = session.get("prefetch_task")
                state._reading_sessions.pop(user_id, None)
            else:
                if state.is_generation_stale(session):
                    state.recover_stale_generation(session, user_id)

                state.touch_session(session)
                return session

        await state.cleanup_prefetch_task(task_to_cleanup)
        return None

    async def try_start_generation(self, user_id: int) -> bool:
        task_to_cleanup: asyncio.Task | None = None
        lock = await state.get_user_session_lock(user_id)

        async with lock:
            session = state._reading_sessions.get(user_id)

            if not session:
                return False

            if state.is_expired(session):
                task_to_cleanup = session.get("prefetch_task")
                state._reading_sessions.pop(user_id, None)
            elif session.get("is_generating"):
                if not state.is_generation_stale(session):
                    return False

                state.recover_stale_generation(session, user_id)
                session["is_generating"] = True
                session["generation_started_at"] = state.now()
                state.touch_session(session)
                return True
            else:
                session["is_generating"] = True
                session["generation_started_at"] = state.now()
                state.touch_session(session)
                return True

        await state.cleanup_prefetch_task(task_to_cleanup)
        return False

    async def update(self, user_id: int, **fields: Any) -> None:
        lock = await state.get_user_session_lock(user_id)

        async with lock:
            session = state._reading_sessions.get(user_id)

            if not session:
                return

            updated_session = dict(session)
            updated_session.update(state.updates_with_generation_metadata(fields))
            session.clear()
            session.update(state.normalized_session_mapping(updated_session))
            state.touch_session(session)

    async def cleanup(self, user_id: int) -> None:
        lock = await state.get_user_session_lock(user_id)

        async with lock:
            session = state._reading_sessions.pop(user_id, None)

        if not session:
            return

        await state.cleanup_session_artifacts(session)

        logger.info(
            "ReadingSessionStore: cleaned session user_id=%s session_id=%s",
            user_id,
            session.get("session_id"),
        )

    async def cleanup_expired(self) -> int:
        expired_user_ids: list[int] = []

        for user_id in list(state._reading_sessions.keys()):
            lock = await state.get_user_session_lock(user_id)

            async with lock:
                session = state._reading_sessions.get(user_id)

                if session and state.is_expired(session):
                    expired_user_ids.append(user_id)

        for user_id in expired_user_ids:
            await self.cleanup(user_id)

        if expired_user_ids:
            logger.info(
                "ReadingSessionStore: cleaned expired sessions: %s",
                len(expired_user_ids),
            )

        return len(expired_user_ids)

    async def cleanup_all(self) -> None:
        for user_id in list(state._reading_sessions.keys()):
            await self.cleanup(user_id)

        await state.clear_user_locks()

        logger.info("ReadingSessionStore: cleaned all sessions")
