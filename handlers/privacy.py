from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import DOCUMENT_HISTORY_RETENTION_DAYS
from database.db import delete_user_private_data
from keyboards.privacy import (
    DELETE_MY_DATA_CANCEL_CALLBACK,
    DELETE_MY_DATA_CONFIRM_CALLBACK,
    delete_my_data_confirmation_keyboard,
)
from texts.privacy import (
    DELETE_MY_DATA_CANCELLED_TEXT,
    DELETE_MY_DATA_CONFIRM_TEXT,
    build_delete_my_data_text,
    build_privacy_text,
)

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

    await message.answer(
        DELETE_MY_DATA_CONFIRM_TEXT,
        parse_mode="HTML",
        reply_markup=delete_my_data_confirmation_keyboard(),
    )


@router.callback_query(F.data == DELETE_MY_DATA_CONFIRM_CALLBACK)
async def delete_my_data_confirm_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if user_id is None:
        await callback.answer("Не вдалося визначити користувача.", show_alert=True)
        return

    result = await delete_user_private_data(user_id)

    if callback.message:
        await callback.message.edit_text(
            build_delete_my_data_text(result),
            parse_mode="HTML",
        )

    await callback.answer("Дані очищено.")


@router.callback_query(F.data == DELETE_MY_DATA_CANCEL_CALLBACK)
async def delete_my_data_cancel_callback(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_text(DELETE_MY_DATA_CANCELLED_TEXT)

    await callback.answer(DELETE_MY_DATA_CANCELLED_TEXT)
