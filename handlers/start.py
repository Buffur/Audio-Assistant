# Файл: handlers/start.py

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from keyboards.main import HELP_BUTTON_TEXT, main_keyboard
from texts.start import HELP_TEXT, START_TEXT

router = Router()


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
    """
    Відправляє коротке привітання та пояснює основний сценарій роботи.
    """
    await message.answer(
        START_TEXT,
        reply_markup=main_keyboard()
    )


@router.message(Command("help"))
@router.message(F.text == HELP_BUTTON_TEXT)
async def help_handler(message: Message) -> None:
    """
    Відправляє коротку інструкцію користувачу.
    """
    await message.answer(HELP_TEXT)