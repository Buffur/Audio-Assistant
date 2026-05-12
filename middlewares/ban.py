# Файл: middlewares/ban.py

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import ADMIN_IDS
from database.db import is_user_banned

logger = logging.getLogger(__name__)

BANNED_TEXT = "🚫 Ваш акаунт заблоковано. Ви не можете користуватися ботом."


class BanMiddleware(BaseMiddleware):
    """
    Глобальна перевірка бану.

    Раніше бан перевірявся тільки в окремих handlers.
    Тепер заблокований користувач не зможе користуватися:
    - /start
    - /settings
    - /usage
    - кнопками читання
    - каталогом
    - будь-якими іншими звичайними діями.
    """

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

        # Адміна не блокуємо middleware.
        if user_id in ADMIN_IDS:
            return await handler(event, data)

        try:
            banned = await is_user_banned(user_id)
        except Exception:
            logger.exception(
                "BanMiddleware: помилка перевірки бану user_id=%s",
                user_id
            )
            return await handler(event, data)

        if not banned:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(BANNED_TEXT, show_alert=True)
            return None

        if isinstance(event, Message):
            await event.answer(BANNED_TEXT)
            return None

        return None