# Файл: middlewares/user_access.py

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from database.db import is_user_banned, register_or_update_user
from texts.messages import ACCOUNT_BLOCKED_TEXT

logger = logging.getLogger(__name__)


class UserAccessMiddleware(BaseMiddleware):
    """
    Middleware для централізованої роботи з користувачем.

    Виконує:
    - перевірку бану;
    - реєстрацію або оновлення користувача в БД;
    - оновлення last_activity.
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

        if await is_user_banned(user_id):
            logger.info(
                "UserAccessMiddleware: заблокований користувач user_id=%s спробував взаємодіяти з ботом",
                user_id
            )

            if isinstance(event, CallbackQuery):
                await event.answer(ACCOUNT_BLOCKED_TEXT, show_alert=True)

            return None

        await register_or_update_user(
            user_id=user_id,
            username=f"@{user.username}" if user.username else "N/A",
            full_name=user.full_name
        )

        return await handler(event, data)