# Файл: keyboards/catalog.py

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CATALOG_OPEN_PREFIX = "catalog_open:"
CATALOG_DELETE_CONFIRM_PREFIX = "catalog_delete_confirm:"
CATALOG_DELETE_PREFIX = "catalog_delete:"
CATALOG_DELETE_CANCEL_PREFIX = "catalog_delete_cancel:"
CATALOG_CLEAR_CONFIRM_CALLBACK = "catalog_clear:confirm"
CATALOG_CLEAR_CANCEL_CALLBACK = "catalog_clear:cancel"
CATALOG_UNAVAILABLE_PREFIX = "catalog_unavailable:"
CATALOG_PAGE_PREFIX = "catalog_page:"


def build_catalog_open_callback(document_id: int) -> str:
    return f"{CATALOG_OPEN_PREFIX}{document_id}"


def build_catalog_delete_callback(document_id: int, page: int = 0) -> str:
    return f"{CATALOG_DELETE_PREFIX}{document_id}:{max(page, 0)}"


def build_catalog_delete_confirm_callback(document_id: int, page: int = 0) -> str:
    return f"{CATALOG_DELETE_CONFIRM_PREFIX}{document_id}:{max(page, 0)}"


def build_catalog_delete_cancel_callback(document_id: int, page: int = 0) -> str:
    return f"{CATALOG_DELETE_CANCEL_PREFIX}{document_id}:{max(page, 0)}"


def build_catalog_unavailable_callback(document_id: int) -> str:
    return f"{CATALOG_UNAVAILABLE_PREFIX}{document_id}"


def build_catalog_page_callback(page: int) -> str:
    return f"{CATALOG_PAGE_PREFIX}{max(page, 0)}"


def parse_catalog_document_id(callback_data: str, prefix: str) -> int | None:
    raw_value = callback_data.replace(prefix, "", 1).split(":", 1)[0]

    if not raw_value.isdigit():
        return None

    return int(raw_value)


def parse_catalog_page(callback_data: str | None, prefix: str) -> int | None:
    if not callback_data:
        return None

    if not callback_data.startswith(prefix):
        return None

    raw_value = callback_data.replace(prefix, "", 1)

    if prefix in {
        CATALOG_DELETE_PREFIX,
        CATALOG_DELETE_CONFIRM_PREFIX,
        CATALOG_DELETE_CANCEL_PREFIX,
    }:
        if ":" not in raw_value:
            return None

        raw_value = raw_value.split(":", 1)[1]

    if not raw_value.isdigit():
        return None

    return int(raw_value)


def catalog_keyboard(
    items: list[dict],
    page: int = 0,
    total_pages: int = 1,
    page_size: int = 5,
) -> InlineKeyboardMarkup | None:
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
    page = max(page, 0)
    total_pages = max(total_pages, 1)

    for index, item in enumerate(items, start=1):
        document_id = int(item["id"])
        has_chunks = bool(item.get("has_chunks"))
        item_number = page * page_size + index

        if has_chunks:
            open_button = InlineKeyboardButton(
                text=f"▶️ Відкрити #{item_number}",
                callback_data=build_catalog_open_callback(document_id)
            )
        else:
            open_button = InlineKeyboardButton(
                text=f"ℹ️ Недоступно #{item_number}",
                callback_data=build_catalog_unavailable_callback(document_id)
            )

        delete_button = InlineKeyboardButton(
            text=f"🗑 Видалити #{item_number}",
            callback_data=build_catalog_delete_confirm_callback(
                document_id,
                page=page,
            )
        )

        keyboard.append([open_button, delete_button])

    navigation_row = []

    if page > 0:
        navigation_row.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=build_catalog_page_callback(page - 1)
            )
        )

    navigation_row.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data=build_catalog_page_callback(page)
        )
    )

    if page + 1 < total_pages:
        navigation_row.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=build_catalog_page_callback(page + 1)
            )
        )

    keyboard.append(navigation_row)

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def catalog_delete_confirmation_keyboard(
    document_id: int,
    page: int = 0,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🗑 Так, видалити",
                callback_data=build_catalog_delete_callback(document_id, page=page),
            ),
        ],
        [
            InlineKeyboardButton(
                text="↩️ Скасувати",
                callback_data=build_catalog_delete_cancel_callback(
                    document_id,
                    page=page,
                ),
            )
        ],
    ])


def catalog_clear_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🧹 Так, очистити",
                callback_data=CATALOG_CLEAR_CONFIRM_CALLBACK,
            )
        ],
        [
            InlineKeyboardButton(
                text="↩️ Скасувати",
                callback_data=CATALOG_CLEAR_CANCEL_CALLBACK,
            )
        ],
    ])
