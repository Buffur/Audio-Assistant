# Файл: middlewares/user_activity.py

import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from database.db import register_or_update_user

logger = logging.getLogger(__name__)

USER_ACTIVITY_UPDATE_INTERVAL_SECONDS = 300.0
USER_ACTIVITY_CACHE_MAX_SIZE = 10_000

_invalidated_user_ids: set[int] = set()


@dataclass(frozen=True)
class UserActivitySnapshot:
    username: str
    full_name: str
    updated_at: float


class UserActivityMiddleware(BaseMiddleware):
    """
    Глобальна реєстрація / оновлення користувача.

    Завдяки цьому користувач потрапляє в базу не тільки після текстового
    повідомлення, а й після:
    - /start
    - /settings
    - /usage
    - /admin
    - callback-кнопок
    """

    def __init__(
        self,
        *,
        update_interval_seconds: float = USER_ACTIVITY_UPDATE_INTERVAL_SECONDS,
        cache_max_size: int = USER_ACTIVITY_CACHE_MAX_SIZE,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._update_interval_seconds = update_interval_seconds
        self._cache_max_size = cache_max_size
        self._monotonic = monotonic
        self._activity_cache: dict[int, UserActivitySnapshot] = {}

    def _should_update_activity(
        self,
        *,
        user_id: int,
        username: str,
        full_name: str,
        now: float,
    ) -> bool:
        if user_id in _invalidated_user_ids:
            return True

        snapshot = self._activity_cache.get(user_id)

        if snapshot is None:
            return True

        if snapshot.username != username or snapshot.full_name != full_name:
            return True

        return now - snapshot.updated_at >= self._update_interval_seconds

    def _remember_activity(
        self,
        *,
        user_id: int,
        username: str,
        full_name: str,
        now: float,
    ) -> None:
        _invalidated_user_ids.discard(user_id)
        self._activity_cache[user_id] = UserActivitySnapshot(
            username=username,
            full_name=full_name,
            updated_at=now,
        )

        if len(self._activity_cache) <= self._cache_max_size:
            return

        oldest_user_id = min(
            self._activity_cache,
            key=lambda cached_user_id: self._activity_cache[cached_user_id].updated_at,
        )
        self._activity_cache.pop(oldest_user_id, None)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any]
    ) -> Any:
        user = getattr(event, "from_user", None)

        if user is None:
            return await handler(event, data)

        username = f"@{user.username}" if user.username else "N/A"
        full_name = user.full_name or "N/A"
        now = self._monotonic()

        if not self._should_update_activity(
            user_id=user.id,
            username=username,
            full_name=full_name,
            now=now,
        ):
            return await handler(event, data)

        try:
            await register_or_update_user(
                user_id=user.id,
                username=username,
                full_name=full_name
            )
            self._remember_activity(
                user_id=user.id,
                username=username,
                full_name=full_name,
                now=now,
            )
        except Exception:
            logger.exception(
                "UserActivityMiddleware: не вдалося оновити користувача user_id=%s",
                user.id
            )

        return await handler(event, data)


def invalidate_user_activity_cache(user_id: int) -> None:
    _invalidated_user_ids.add(user_id)
