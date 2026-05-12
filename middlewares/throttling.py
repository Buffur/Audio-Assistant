# Файл: middlewares/throttling.py

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import ADMIN_IDS

RATE_LIMIT_TEXT = "⏳ Зачекайте кілька секунд перед наступною дією."


class ThrottlingMiddleware(BaseMiddleware):
    """
    Простий in-memory rate limit.

    Для MVP цього достатньо.
    RedisRateLimitMiddleware поки не підключаємо,
    бо у наданих файлах я не бачу services/redis_client.py,
    а без нього імпорт може зламати запуск.
    """

    def __init__(self, rate_limit: float = 1.5) -> None:
        self.cache: dict[int, float] = {}
        self.rate_limit = rate_limit

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

        if user_id in ADMIN_IDS:
            return await handler(event, data)

        current_time = time.time()
        last_time = self.cache.get(user_id)

        if last_time is not None:
            time_passed = current_time - last_time

            if time_passed < self.rate_limit:
                if isinstance(event, CallbackQuery):
                    await event.answer(RATE_LIMIT_TEXT, show_alert=True)
                elif isinstance(event, Message):
                    await event.answer(RATE_LIMIT_TEXT)

                return None

        self.cache[user_id] = current_time

        return await handler(event, data)