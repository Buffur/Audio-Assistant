# Файл: keyboards/catalog.py

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CATALOG_OPEN_PREFIX = "catalog_open:"
CATALOG_DELETE_PREFIX = "catalog_delete:"
CATALOG_UNAVAILABLE_PREFIX = "catalog_unavailable:"


def build_catalog_open_callback(document_id: int) -> str:
    return f"{CATALOG_OPEN_PREFIX}{document_id}"


def build_catalog_delete_callback(document_id: int) -> str:
    return f"{CATALOG_DELETE_PREFIX}{document_id}"


def build_catalog_unavailable_callback(document_id: int) -> str:
    return f"{CATALOG_UNAVAILABLE_PREFIX}{document_id}"


def parse_catalog_document_id(callback_data: str, prefix: str) -> int | None:
    raw_value = callback_data.replace(prefix, "", 1)

    if not raw_value.isdigit():
        return None

    return int(raw_value)


def catalog_keyboard(items: list[dict]) -> InlineKeyboardMarkup | None:
    """
    Inline-клавіатура каталогу.

    Для кожного документа:
    - якщо chunks є — показуємо «Відкрити»;
    - якщо chunks немає — показуємо «Недоступно»;
    - завжди показуємо «Видалити».
    """
    if not items:
        return None

    keyboard = []

    for index, item in enumerate(items, start=1):
        document_id = int(item["id"])
        has_chunks = bool(item.get("has_chunks"))

        if has_chunks:
            open_button = InlineKeyboardButton(
                text=f"▶️ Відкрити #{index}",
                callback_data=build_catalog_open_callback(document_id)
            )
        else:
            open_button = InlineKeyboardButton(
                text=f"ℹ️ Недоступно #{index}",
                callback_data=build_catalog_unavailable_callback(document_id)
            )

        delete_button = InlineKeyboardButton(
            text=f"🗑 Видалити #{index}",
            callback_data=build_catalog_delete_callback(document_id)
        )

        keyboard.append([open_button, delete_button])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)