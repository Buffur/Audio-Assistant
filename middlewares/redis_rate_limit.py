# Файл: middlewares/redis_rate_limit.py

import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import ADMIN_IDS
from middlewares.rate_limit import RateLimitMiddleware
from services.redis_client import get_redis_client
from texts.messages import RATE_LIMIT_TEXT

logger = logging.getLogger(__name__)

RATE_LIMIT_LUA_SCRIPT = """
local key = KEYS[1]
local min_allowed_time = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local event_id = ARGV[3]
local period_seconds = tonumber(ARGV[4])
local max_events = tonumber(ARGV[5])

redis.call("ZREMRANGEBYSCORE", key, "-inf", min_allowed_time)

local current_events_count = redis.call("ZCARD", key)

if current_events_count >= max_events then
    redis.call("EXPIRE", key, period_seconds)
    return 0
end

redis.call("ZADD", key, now, event_id)
redis.call("EXPIRE", key, period_seconds)

return 1
""".strip()


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
        self._fallback_limiter = RateLimitMiddleware(
            max_events=max_events,
            period_seconds=period_seconds,
            warning_cooldown_seconds=warning_cooldown_seconds,
        )

    def _events_key(self, user_id: int) -> str:
        return f"rate_limit:events:{user_id}"

    def _warning_key(self, user_id: int) -> str:
        return f"rate_limit:warning:{user_id}"

    async def _is_allowed(self, user_id: int, now: float) -> bool:
        client = await get_redis_client()

        key = self._events_key(user_id)
        min_allowed_time = now - self.period_seconds

        event_id = f"{now}:{user_id}:{uuid.uuid4().hex}"

        result = await client.eval(
            RATE_LIMIT_LUA_SCRIPT,
            1,
            key,
            min_allowed_time,
            now,
            event_id,
            self.period_seconds,
            self.max_events,
        )

        return bool(result)

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

        if user_id in ADMIN_IDS:
            return await handler(event, data)

        try:
            is_allowed = await self._is_allowed(user_id, now)
        except Exception:
            logger.exception(
                "RedisRateLimitMiddleware: Redis помилка, використовую in-memory fallback user_id=%s",
                user_id
            )
            return await self._fallback_limiter(handler, event, data)

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
