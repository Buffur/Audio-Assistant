from collections.abc import Callable
from typing import Any

from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from texts.admin_menu import ADMIN_ACCESS_DENIED_TEXT


CALLBACK_OWNER_MISMATCH_TEXT = "Ця кнопка належить іншому користувачу."
CALLBACK_MESSAGE_MISSING_TEXT = "Не вдалося знайти повідомлення для цієї дії."
USER_MISSING_TEXT = "Не вдалося визначити користувача."
PRIVATE_CHAT_REQUIRED_TEXT = "Ця дія доступна тільки в приватному чаті з ботом."


def is_admin_user_id(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


def message_user_id(message: Message) -> int | None:
    user = getattr(message, "from_user", None)
    user_id = getattr(user, "id", None)

    return user_id if isinstance(user_id, int) else None


def callback_user_id(callback: CallbackQuery) -> int | None:
    user = getattr(callback, "from_user", None)
    user_id = getattr(user, "id", None)

    return user_id if isinstance(user_id, int) else None


def message_chat_type(message: Message) -> str | None:
    chat = getattr(message, "chat", None)
    chat_type = getattr(chat, "type", None)

    return chat_type if isinstance(chat_type, str) else None


def callback_chat_type(callback: CallbackQuery) -> str | None:
    message = getattr(callback, "message", None)

    if message is None:
        return None

    return message_chat_type(message)


def is_private_message(message: Message) -> bool:
    return message_chat_type(message) == "private"


def is_private_callback(callback: CallbackQuery) -> bool:
    return callback_chat_type(callback) == "private"


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


async def require_message_user(
    message: Message,
    *,
    text: str = USER_MISSING_TEXT,
) -> int | None:
    user_id = message_user_id(message)

    if user_id is None:
        await message.answer(text)
        return None

    return user_id


async def require_callback_user(
    callback: CallbackQuery,
    *,
    alert_text: str = USER_MISSING_TEXT,
) -> int | None:
    user_id = callback_user_id(callback)

    if user_id is None:
        await callback.answer(alert_text, show_alert=True)
        return None

    return user_id


async def require_private_message(
    message: Message,
    *,
    text: str = PRIVATE_CHAT_REQUIRED_TEXT,
) -> bool:
    if is_private_message(message):
        return True

    await message.answer(text)
    return False


async def require_private_callback(
    callback: CallbackQuery,
    *,
    alert_text: str = PRIVATE_CHAT_REQUIRED_TEXT,
) -> bool:
    if is_private_callback(callback):
        return True

    await callback.answer(alert_text, show_alert=True)
    return False


async def require_admin_message(
    message: Message,
    *,
    denied_text: str = ADMIN_ACCESS_DENIED_TEXT,
) -> int | None:
    user_id = await require_private_message_user(message)

    if user_id is None:
        return None

    if not is_admin_user_id(user_id):
        await message.answer(denied_text)
        return None

    return user_id


async def require_admin_callback(
    callback: CallbackQuery,
    *,
    denied_text: str = ADMIN_ACCESS_DENIED_TEXT,
) -> int | None:
    user_id = await require_private_callback_user(callback)

    if user_id is None:
        return None

    if not is_admin_user_id(user_id):
        await callback.answer(denied_text, show_alert=True)
        return None

    return user_id


async def require_private_message_user(message: Message) -> int | None:
    if not await require_private_message(message):
        return None

    return await require_message_user(message)


async def require_private_callback_user(callback: CallbackQuery) -> int | None:
    if not await require_private_callback(callback):
        return None

    return await require_callback_user(callback)


async def require_parsed_callback_owner(
    callback: CallbackQuery,
    owner_parser: Callable[[str | None], int | None],
    *,
    alert_text: str = CALLBACK_OWNER_MISMATCH_TEXT,
) -> int | None:
    user_id = await require_private_callback_user(callback)

    if user_id is None:
        return None

    try:
        owner_id = owner_parser(callback.data)
    except Exception:
        # Malformed callback payloads must fail closed at the handler boundary.
        owner_id = None

    if owner_id != user_id:
        await callback.answer(alert_text, show_alert=True)
        return None

    return user_id


async def require_callback_message(
    callback: CallbackQuery,
    *,
    alert_text: str = CALLBACK_MESSAGE_MISSING_TEXT,
) -> Any | None:
    if callback.message is None:
        await callback.answer(alert_text, show_alert=True)
        return None

    return callback.message
