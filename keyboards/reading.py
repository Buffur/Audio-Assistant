# Файл: keyboards/reading.py

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

READ_NEXT_ACTION = "read_next"
READ_SUMMARY_ACTION = "read_summary"
READ_STOP_ACTION = "read_stop"

CALLBACK_SEPARATOR = ":"


def build_reading_callback(action: str, session_id: str) -> str:
    """
    Формує callback_data для кнопок читання.

    Приклад:
    read_next:abc123
    read_summary:abc123
    read_stop:abc123
    """
    return f"{action}{CALLBACK_SEPARATOR}{session_id}"


def parse_reading_callback(callback_data: str) -> tuple[str, str | None]:
    """
    Розбирає callback_data кнопки читання.

    Повертає:
    - action;
    - session_id або None для старого формату callback без session_id.
    """
    if CALLBACK_SEPARATOR not in callback_data:
        return callback_data, None

    action, session_id = callback_data.split(CALLBACK_SEPARATOR, 1)

    return action, session_id or None


def reading_navigation_keyboard(
    has_next: bool,
    session_id: str
) -> InlineKeyboardMarkup:
    """
    Клавіатура для навігації під час читання основного тексту.

    Якщо є наступна частина, додається кнопка «Слухати далі».
    Кнопки «Короткий зміст» і «Закінчити» доступні завжди.
    """
    keyboard = []

    if has_next:
        keyboard.append([
            InlineKeyboardButton(
                text="▶️ Слухати далі",
                callback_data=build_reading_callback(
                    READ_NEXT_ACTION,
                    session_id
                )
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="📝 Короткий зміст",
            callback_data=build_reading_callback(
                READ_SUMMARY_ACTION,
                session_id
            )
        ),
        InlineKeyboardButton(
            text="⏹ Закінчити",
            callback_data=build_reading_callback(
                READ_STOP_ACTION,
                session_id
            )
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def summary_only_keyboard(session_id: str) -> InlineKeyboardMarkup:
    """
    Клавіатура для попередніх voice-повідомлень.

    Коли користувач натиснув «Слухати далі», ми прибираємо тільки цю кнопку,
    але залишаємо «Короткий зміст» і «Закінчити».
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📝 Короткий зміст",
                callback_data=build_reading_callback(
                    READ_SUMMARY_ACTION,
                    session_id
                )
            ),
            InlineKeyboardButton(
                text="⏹ Закінчити",
                callback_data=build_reading_callback(
                    READ_STOP_ACTION,
                    session_id
                )
            ),
        ]
    ])


def summary_navigation_keyboard(
    has_next: bool,
    session_id: str
) -> InlineKeyboardMarkup:
    """
    Клавіатура після короткого змісту.

    Якщо оригінальний текст ще не дочитаний,
    додається кнопка продовження читання.
    """
    keyboard = []

    if has_next:
        keyboard.append([
            InlineKeyboardButton(
                text="▶️ Продовжити читання оригіналу",
                callback_data=build_reading_callback(
                    READ_NEXT_ACTION,
                    session_id
                )
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="⏹ Закінчити",
            callback_data=build_reading_callback(
                READ_STOP_ACTION,
                session_id
            )
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)