from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import DOCUMENT_HISTORY_RETENTION_DAYS
from database.db import delete_user_private_data
from handlers.callback_guards import (
    CALLBACK_OWNER_MISMATCH_TEXT,
    USER_MISSING_TEXT,
    callback_user_id,
    message_user_id,
    parsed_callback_owner_matches,
)
from keyboards.privacy import (
    DELETE_MY_DATA_CANCEL_CALLBACK,
    DELETE_MY_DATA_CONFIRM_CALLBACK,
    delete_my_data_confirmation_keyboard,
    parse_delete_my_data_callback_user_id,
)
from services.reading_service import cleanup_user_private_runtime_data
from texts.privacy import (
    DELETE_MY_DATA_CANCELLED_TEXT,
    DELETE_MY_DATA_CONFIRM_TEXT,
    build_delete_my_data_text,
    build_privacy_text,
)

router = Router()


def _callback_owner_matches(callback: CallbackQuery) -> bool:
    return parsed_callback_owner_matches(
        callback,
        parse_delete_my_data_callback_user_id,
    )


@router.message(Command("privacy"))
async def privacy_handler(message: Message) -> None:
    await message.answer(
        build_privacy_text(DOCUMENT_HISTORY_RETENTION_DAYS),
        parse_mode="HTML",
    )


@router.message(Command("delete_my_data"))
async def delete_my_data_handler(message: Message) -> None:
    user_id = message_user_id(message)

    if user_id is None:
        await message.answer(USER_MISSING_TEXT)
        return

    await message.answer(
        DELETE_MY_DATA_CONFIRM_TEXT,
        parse_mode="HTML",
        reply_markup=delete_my_data_confirmation_keyboard(user_id),
    )


@router.callback_query(F.data.startswith(DELETE_MY_DATA_CONFIRM_CALLBACK))
async def delete_my_data_confirm_callback(callback: CallbackQuery) -> None:
    user_id = callback_user_id(callback)

    if user_id is None:
        await callback.answer(USER_MISSING_TEXT, show_alert=True)
        return

    if not _callback_owner_matches(callback):
        await callback.answer(CALLBACK_OWNER_MISMATCH_TEXT, show_alert=True)
        return

    runtime_result = await cleanup_user_private_runtime_data(user_id)
    result = await delete_user_private_data(user_id)
    result.update(runtime_result)

    if callback.message:
        await callback.message.edit_text(
            build_delete_my_data_text(result),
            parse_mode="HTML",
        )

    await callback.answer("Дані очищено.")


@router.callback_query(F.data.startswith(DELETE_MY_DATA_CANCEL_CALLBACK))
async def delete_my_data_cancel_callback(callback: CallbackQuery) -> None:
    if not _callback_owner_matches(callback):
        await callback.answer(CALLBACK_OWNER_MISMATCH_TEXT, show_alert=True)
        return

    if callback.message:
        await callback.message.edit_text(DELETE_MY_DATA_CANCELLED_TEXT)

    await callback.answer(DELETE_MY_DATA_CANCELLED_TEXT)
