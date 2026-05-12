# Файл: middlewares/redis_rate_limit.py

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from services.redis_client import get_redis_client
from texts.messages import RATE_LIMIT_TEXT

logger = logging.getLogger(__name__)


class RedisRateLimitMiddleware(BaseMiddleware):
    """
    Redis-based rate limiter.

    На відміну від in-memory rate limiter:
    - працює між кількома процесами;
    - не скидається при рестарті одного Python-процесу;
    - краще підходить для production.

    Алгоритм:
    - для кожного user_id зберігаємо sorted set з timestamps;
    - видаляємо старі timestamps;
    - рахуємо події за останній period_seconds;
    - якщо подій забагато — блокуємо поточну подію.
    """

    def __init__(
        self,
        max_events: int = 8,
        period_seconds: int = 10,
        warning_cooldown_seconds: int = 10
    ) -> None:
        self.max_events = max_events
        self.period_seconds = period_seconds
        self.warning_cooldown_seconds = warning_cooldown_seconds

    def _events_key(self, user_id: int) -> str:
        return f"rate_limit:events:{user_id}"

    def _warning_key(self, user_id: int) -> str:
        return f"rate_limit:warning:{user_id}"

    async def _is_allowed(self, user_id: int, now: float) -> bool:
        client = await get_redis_client()

        key = self._events_key(user_id)
        min_allowed_time = now - self.period_seconds

        async with client.pipeline(transaction=True) as pipe:
            await pipe.zremrangebyscore(key, 0, min_allowed_time)
            await pipe.zcard(key)
            results = await pipe.execute()

        current_events_count = int(results[1])

        if current_events_count >= self.max_events:
            await client.expire(key, self.period_seconds)
            return False

        event_id = f"{now}:{user_id}"

        async with client.pipeline(transaction=True) as pipe:
            await pipe.zadd(key, {event_id: now})
            await pipe.expire(key, self.period_seconds)
            await pipe.execute()

        return True

    async def _can_send_warning(self, user_id: int) -> bool:
        client = await get_redis_client()

        key = self._warning_key(user_id)

        was_set = await client.set(
            key,
            "1",
            ex=self.warning_cooldown_seconds,
            nx=True
        )

        return bool(was_set)

    async def _notify_user(self, event: TelegramObject, user_id: int) -> None:
        if not await self._can_send_warning(user_id):
            return

        if isinstance(event, CallbackQuery):
            await event.answer(RATE_LIMIT_TEXT, show_alert=True)
            return

        if isinstance(event, Message):
            await event.answer(RATE_LIMIT_TEXT)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any]
    ) -> Any:
        user = getattr(event, "from_user", None)

        if user is None:
            return await handler(event, data)

        user_id = user.id
        now = time.time()

        try:
            is_allowed = await self._is_allowed(user_id, now)
        except Exception:
            logger.exception(
                "RedisRateLimitMiddleware: Redis помилка, пропускаю подію без rate limit user_id=%s",
                user_id
            )
            return await handler(event, data)

        if not is_allowed:
            logger.warning(
                "RedisRateLimitMiddleware: user_id=%s перевищив ліміт %s подій за %s секунд",
                user_id,
                self.max_events,
                self.period_seconds
            )

            await self._notify_user(event, user_id)
            return None

        return await handler(event, data)