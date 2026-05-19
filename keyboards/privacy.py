from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

DELETE_MY_DATA_CONFIRM_CALLBACK = "privacy:delete_my_data_confirm"
DELETE_MY_DATA_CANCEL_CALLBACK = "privacy:delete_my_data_cancel"


def delete_my_data_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Так, очистити",
                callback_data=DELETE_MY_DATA_CONFIRM_CALLBACK,
            ),
            InlineKeyboardButton(
                text="↩️ Скасувати",
                callback_data=DELETE_MY_DATA_CANCEL_CALLBACK,
            ),
        ]
    ])
