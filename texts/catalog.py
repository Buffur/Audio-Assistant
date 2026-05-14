# Файл: texts/catalog.py

import html

EMPTY_CATALOG_TEXT = (
    "📭 Каталог порожній.\n\n"
    "Надішліть текст, документ, фото або посилання — і після обробки "
    "матеріал зʼявиться в каталозі."
)

CATALOG_CLEARED_TEXT = "🧹 Каталог документів очищено."

CATALOG_DOCUMENT_NOT_FOUND_TEXT = (
    "❌ Документ не знайдено. Можливо, він був видалений."
)

CATALOG_DOCUMENT_WITHOUT_CHUNKS_TEXT = (
    "ℹ️ Цей запис не можна відкрити повторно, бо він був створений "
    "до появи повноцінного каталогу.\n\n"
    "Нові документи, які ви надішлете після оновлення, вже можна буде відкривати повторно."
)

CATALOG_DOCUMENT_DELETED_TEXT = "🗑 Документ видалено з каталогу."

CATALOG_OPENING_TEXT = "⏳ Відкриваю документ з каталогу..."

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

    status = "✅ Можна відкрити" if has_chunks else "⚠️ Старий запис, повторне відкриття недоступне"

    return (
        f"{index}. <b>{source_type}</b> — {source_name}\n"
        f"   🕒 {created_at}\n"
        f"   🔠 Символів: {text_length}\n"
        f"   🎧 Частин: {chunks_count}\n"
        f"   {status}\n"
        f"   <i>{preview}</i>"
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
        "📚 <b>Каталог документів:</b>\n",
        f"Сторінка {page + 1} з {total_pages}. "
        f"Показано {len(items)} з {total_items}.\n"
    ]

    for index, item in enumerate(items, start=page * page_size + 1):
        parts.append(format_catalog_item(index, item))

    parts.append(
        "\nНатисніть «Відкрити», щоб повернутися до документа.\n"
        "/catalog_clear — очистити каталог"
    )

    return "\n\n".join(parts)


def build_catalog_document_opened_text(source_name: str, chunks_count: int) -> str:
    safe_source_name = html.escape(source_name or "Документ")

    return (
        f"📖 Відкрито з каталогу: <b>{safe_source_name}</b>\n\n"
        f"🎧 Частин: {chunks_count}"
    )
