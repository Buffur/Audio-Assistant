# Файл: handlers/start.py

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from handlers.callback_guards import require_private_message_user
from keyboards.main import HELP_BUTTON_TEXT, main_keyboard
from texts.start import HELP_TEXT, START_TEXT

router = Router()


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
    """
    Відправляє коротке привітання та пояснює основний сценарій роботи.
    """
    if await require_private_message_user(message) is None:
        return

    await message.answer(
        START_TEXT,
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@router.message(F.text == HELP_BUTTON_TEXT)
async def help_handler(message: Message) -> None:
    """
    Відправляє коротку інструкцію користувачу.
    """
    if await require_private_message_user(message) is None:
        return

    await message.answer(HELP_TEXT, parse_mode="HTML")
