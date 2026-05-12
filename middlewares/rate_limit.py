# Файл: middlewares/rate_limit.py

import logging
import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import ADMIN_IDS
from texts.messages import RATE_LIMIT_TEXT

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseMiddleware):
    """
    Простий in-memory rate limiter.

    Обмежує кількість подій від одного користувача
    за короткий проміжок часу.

    Це захищає бота від spam/flood і зменшує ризик
    перевантаження TTS/OCR/AI pipeline.
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

        self._user_events: dict[int, deque[float]] = defaultdict(deque)
        self._last_warning_time: dict[int, float] = {}

    def _cleanup_old_events(self, user_id: int, now: float) -> None:
        events = self._user_events[user_id]

        while events and now - events[0] > self.period_seconds:
            events.popleft()

        if not events:
            self._user_events.pop(user_id, None)

    def _is_allowed(self, user_id: int, now: float) -> bool:
        self._cleanup_old_events(user_id, now)

        events = self._user_events[user_id]

        if len(events) >= self.max_events:
            return False

        events.append(now)
        return True

    def _can_send_warning(self, user_id: int, now: float) -> bool:
        last_warning = self._last_warning_time.get(user_id)

        if last_warning is None:
            self._last_warning_time[user_id] = now
            return True

        if now - last_warning >= self.warning_cooldown_seconds:
            self._last_warning_time[user_id] = now
            return True

        return False

    async def _notify_user(
        self,
        event: TelegramObject,
        user_id: int,
        now: float
    ) -> None:
        if not self._can_send_warning(user_id, now):
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

        # Адмінів не обмежуємо.
        if user_id in ADMIN_IDS:
            return await handler(event, data)

        now = time.monotonic()

        if not self._is_allowed(user_id, now):
            logger.warning(
                "RateLimitMiddleware: user_id=%s перевищив ліміт %s подій за %s секунд",
                user_id,
                self.max_events,
                self.period_seconds
            )

            await self._notify_user(event, user_id, now)
            return None

        return await handler(event, data)