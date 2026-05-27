from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import DOCUMENT_HISTORY_RETENTION_DAYS
from database.db import delete_user_private_data
from handlers.callback_guards import (
    require_parsed_callback_owner,
    require_private_message_user,
)
from keyboards.privacy import (
    DELETE_MY_DATA_CANCEL_CALLBACK,
    DELETE_MY_DATA_CONFIRM_CALLBACK,
    delete_my_data_confirmation_keyboard,
    parse_delete_my_data_callback_user_id,
)
from middlewares.user_activity import invalidate_user_activity_cache
from services.reading_service import cleanup_user_private_runtime_data
from texts.privacy import (
    DELETE_MY_DATA_CANCELLED_TEXT,
    DELETE_MY_DATA_CONFIRM_TEXT,
    build_delete_my_data_text,
    build_privacy_text,
)

router = Router()


@router.message(Command("privacy"))
async def privacy_handler(message: Message) -> None:
    if await require_private_message_user(message) is None:
        return

    await message.answer(
        build_privacy_text(DOCUMENT_HISTORY_RETENTION_DAYS),
        parse_mode="HTML",
    )


@router.message(Command("delete_my_data"))
async def delete_my_data_handler(message: Message) -> None:
    user_id = await require_private_message_user(message)

    if user_id is None:
        return

    await message.answer(
        DELETE_MY_DATA_CONFIRM_TEXT,
        parse_mode="HTML",
        reply_markup=delete_my_data_confirmation_keyboard(user_id),
    )


@router.callback_query(F.data.startswith(DELETE_MY_DATA_CONFIRM_CALLBACK))
async def delete_my_data_confirm_callback(callback: CallbackQuery) -> None:
    user_id = await require_parsed_callback_owner(
        callback,
        parse_delete_my_data_callback_user_id,
    )

    if user_id is None:
        return

    runtime_result = await cleanup_user_private_runtime_data(user_id)
    result = await delete_user_private_data(user_id)
    invalidate_user_activity_cache(user_id)
    result.update(runtime_result)

    if callback.message:
        await callback.message.edit_text(
            build_delete_my_data_text(result),
            parse_mode="HTML",
        )

    await callback.answer("Дані очищено.")


@router.callback_query(F.data.startswith(DELETE_MY_DATA_CANCEL_CALLBACK))
async def delete_my_data_cancel_callback(callback: CallbackQuery) -> None:
    if await require_parsed_callback_owner(
        callback,
        parse_delete_my_data_callback_user_id,
    ) is None:
        return

    if callback.message:
        await callback.message.edit_text(DELETE_MY_DATA_CANCELLED_TEXT)

    await callback.answer(DELETE_MY_DATA_CANCELLED_TEXT)
