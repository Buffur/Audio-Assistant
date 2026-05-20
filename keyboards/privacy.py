from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

DELETE_MY_DATA_CONFIRM_CALLBACK = "privacy:delete_my_data_confirm"
DELETE_MY_DATA_CANCEL_CALLBACK = "privacy:delete_my_data_cancel"


def build_delete_my_data_confirm_callback(user_id: int) -> str:
    return f"{DELETE_MY_DATA_CONFIRM_CALLBACK}:{user_id}"


def build_delete_my_data_cancel_callback(user_id: int) -> str:
    return f"{DELETE_MY_DATA_CANCEL_CALLBACK}:{user_id}"


def parse_delete_my_data_callback_user_id(callback_data: str | None) -> int | None:
    if not callback_data or ":" not in callback_data:
        return None

    raw_user_id = callback_data.rsplit(":", 1)[-1]

    if not raw_user_id.isdigit():
        return None

    return int(raw_user_id)


def delete_my_data_confirmation_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Так, очистити",
                callback_data=build_delete_my_data_confirm_callback(user_id),
            ),
            InlineKeyboardButton(
                text="↩️ Скасувати",
                callback_data=build_delete_my_data_cancel_callback(user_id),
            ),
        ]
    ])
