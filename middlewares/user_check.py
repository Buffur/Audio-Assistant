from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from database.db import register_or_update_user, is_user_banned

class UserCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user:
            # 1. Перевірка на бан (перехоплюємо ДО виконання коду бота)
            if await is_user_banned(user.id):
                if isinstance(event, CallbackQuery):
                    await event.answer("🚫 Ваш акаунт заблоковано.", show_alert=True)
                return # Зупиняємо обробку
            
            # 2. Автоматична реєстрація або оновлення часу активності
            await register_or_update_user(
                user_id=user.id,
                username=f"@{user.username}" if user.username else "N/A",
                full_name=user.full_name
            )

        return await handler(event, data)