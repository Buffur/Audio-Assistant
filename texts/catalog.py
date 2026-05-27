# Файл: texts/catalog.py

import html

EMPTY_CATALOG_TEXT = (
    "📭 Каталог порожній.\n\n"
    "Надішліть текст, документ, фото або посилання — і після обробки "
    "матеріал зʼявиться в каталозі."
)

CATALOG_CLEARED_TEXT = "🧹 Каталог очищено."
CATALOG_CLEAR_CONFIRM_TEXT = (
    "Очистити весь каталог?\n\n"
    "Цю дію не можна скасувати."
)
CATALOG_CLEAR_CANCELLED_TEXT = "Очищення каталогу скасовано."

CATALOG_DOCUMENT_NOT_FOUND_TEXT = (
    "❌ Документ не знайдено. Можливо, він був видалений."
)

CATALOG_DOCUMENT_WITHOUT_CHUNKS_TEXT = (
    "ℹ️ Цей запис не можна відкрити повторно, бо він був створений "
    "до появи повноцінного каталогу.\n\n"
    "Нові документи, які ви надішлете після оновлення, вже можна буде відкривати повторно."
)

CATALOG_DOCUMENT_DELETED_TEXT = "🗑 Документ видалено з каталогу."
CATALOG_DELETE_CONFIRM_TEXT = (
    "Видалити цей документ з каталогу?\n\n"
    "Цю дію не можна скасувати."
)

CATALOG_OPENING_TEXT = "⏳ Відкриваю документ і готую першу частину аудіо..."

CATALOG_HELP_TEXT = (
    "📚 Команди каталогу:\n\n"
    "/catalog — показати каталог документів\n"
    "/history — те саме, що /catalog\n"
    "/catalog_clear — очистити каталог\n"
    "/history_clear — те саме, що /catalog_clear"
)

SOURCE_TYPE_LABELS = {
    "text": "Текст",
    "url": "Посилання",
    "photo": "Фото",
    "document": "Документ",
    "unknown": "Невідомо",
}


def format_catalog_item(index: int, item: dict) -> str:
    source_type = SOURCE_TYPE_LABELS.get(
        item.get("source_type"),
        item.get("source_type", "Невідомо")
    )

    source_name = html.escape(str(item.get("source_name") or "Без назви"))
    text_length = int(item.get("text_length", 0))
    chunks_count = int(item.get("chunks_count", 0))
    created_at = html.escape(str(item.get("created_at") or "Невідомо"))
    preview = html.escape(str(item.get("text_preview") or "Без превʼю"))
    has_chunks = bool(item.get("has_chunks"))

    status = "✅ Доступний для повторного відкриття" if has_chunks else "⚠️ Повторне відкриття недоступне"

    return (
        f"<b>{index}. {source_type}</b>\n"
        f"📌 {source_name}\n"
        f"🕒 {created_at}\n"
        f"📖 {text_length} символів · 🎧 {chunks_count} частин\n"
        f"{status}\n"
        f"<i>{preview}</i>"
    )


def build_catalog_text(
    items: list[dict],
    page: int = 0,
    total_pages: int = 1,
    total_items: int | None = None,
    page_size: int = 5,
) -> str:
    if not items:
        return EMPTY_CATALOG_TEXT

    total_pages = max(total_pages, 1)
    total_items = len(items) if total_items is None else total_items

    parts = [
        "📚 <b>Каталог</b>\n",
        f"Сторінка {page + 1} з {total_pages} · "
        f"показано {len(items)} з {total_items}"
    ]

    for index, item in enumerate(items, start=page * page_size + 1):
        parts.append(format_catalog_item(index, item))

    parts.append(
        "\nНатисніть «Слухати», щоб почати озвучку документа з початку.\n"
        "/catalog_clear — очистити каталог"
    )

    return "\n\n".join(parts)


def build_catalog_document_opened_text(source_name: str, chunks_count: int) -> str:
    safe_source_name = html.escape(source_name or "Документ")

    return (
        f"📖 Відкрито з каталогу: <b>{safe_source_name}</b>\n\n"
        f"🎧 Частин для прослуховування: {chunks_count}"
    )
