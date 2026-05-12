# Файл: keyboards/main.py

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

SETTINGS_BUTTON_TEXT = "⚙️ Налаштування"
HELP_BUTTON_TEXT = "❓ Довідка"


def main_keyboard() -> ReplyKeyboardMarkup:
    """
    Головна reply-клавіатура бота.

    Відображається внизу екрана та дає швидкий доступ
    до налаштувань і довідки.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=SETTINGS_BUTTON_TEXT),
                KeyboardButton(text=HELP_BUTTON_TEXT),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Надішліть текст, файл, фото або посилання..."
    )