# Файл: handlers/history.py

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services.document_history_service import (
    clear_document_history,
    get_recent_document_history,
)
from texts.history import (
    HISTORY_CLEARED_TEXT,
    HISTORY_HELP_TEXT,
    build_history_text,
)

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("history"))
async def history_handler(message: Message) -> None:
    """
    Показує останні оброблені матеріали користувача.
    """
    user_id = message.from_user.id

    items = await get_recent_document_history(user_id=user_id)
    text = build_history_text(items)

    await message.answer(text, parse_mode="HTML")


@router.message(Command("history_clear"))
async def history_clear_handler(message: Message) -> None:
    """
    Очищає історію матеріалів користувача.
    """
    user_id = message.from_user.id

    await clear_document_history(user_id=user_id)
    await message.answer(HISTORY_CLEARED_TEXT)


@router.message(Command("history_help"))
async def history_help_handler(message: Message) -> None:
    """
    Показує довідку по історії.
    """
    await message.answer(HISTORY_HELP_TEXT)