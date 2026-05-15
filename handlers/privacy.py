from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import DOCUMENT_HISTORY_RETENTION_DAYS
from database.db import delete_user_private_data
from texts.privacy import build_delete_my_data_text, build_privacy_text

router = Router()


@router.message(Command("privacy"))
async def privacy_handler(message: Message) -> None:
    await message.answer(
        build_privacy_text(DOCUMENT_HISTORY_RETENTION_DAYS),
        parse_mode="HTML",
    )


@router.message(Command("delete_my_data"))
async def delete_my_data_handler(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None

    if user_id is None:
        await message.answer("Не вдалося визначити користувача.")
        return

    result = await delete_user_private_data(user_id)

    await message.answer(
        build_delete_my_data_text(result),
        parse_mode="HTML",
    )
