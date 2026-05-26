from collections.abc import Callable
from typing import Any

from aiogram.types import CallbackQuery, Message


CALLBACK_OWNER_MISMATCH_TEXT = "Ця кнопка належить іншому користувачу."
CALLBACK_MESSAGE_MISSING_TEXT = "Не вдалося знайти повідомлення для цієї дії."
USER_MISSING_TEXT = "Не вдалося визначити користувача."


def message_user_id(message: Message) -> int | None:
    user = getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)

    return user_id if isinstance(user_id, int) else None


def callback_user_id(callback: CallbackQuery) -> int | None:
    user = getattr(callback, "from_user", None)
    user_id = getattr(user, "id", None)

    return user_id if isinstance(user_id, int) else None


def callback_owner_matches(
    callback: CallbackQuery,
    owner_id: int | None,
) -> bool:
    user_id = callback_user_id(callback)

    return user_id is not None and (owner_id is None or owner_id == user_id)


def parsed_callback_owner_matches(
    callback: CallbackQuery,
    owner_parser: Callable[[str | None], int | None],
) -> bool:
    return callback_owner_matches(callback, owner_parser(callback.data))


async def require_callback_message(
    callback: CallbackQuery,
    *,
    alert_text: str = CALLBACK_MESSAGE_MISSING_TEXT,
) -> Any | None:
    if callback.message is None:
        await callback.answer(alert_text, show_alert=True)
        return None

    return callback.message
