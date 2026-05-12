# Файл: middlewares/user_activity.py

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from database.db import register_or_update_user

logger = logging.getLogger(__name__)


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

        try:
            await register_or_update_user(
                user_id=user.id,
                username=username,
                full_name=full_name
            )
        except Exception:
            logger.exception(
                "UserActivityMiddleware: не вдалося оновити користувача user_id=%s",
                user.id
            )

        return await handler(event, data)