# Файл: texts/history.py

EMPTY_HISTORY_TEXT = (
    "📭 Історія порожня.\n\n"
    "Надішліть текст, документ, фото або посилання — і після обробки "
    "цей матеріал зʼявиться в історії."
)

HISTORY_CLEARED_TEXT = "🧹 Історію документів очищено."

HISTORY_HELP_TEXT = (
    "📚 Команди історії:\n\n"
    "/history — показати останні матеріали\n"
    "/history_clear — очистити історію"
)

SOURCE_TYPE_LABELS = {
    "text": "Текст",
    "url": "Посилання",
    "photo": "Фото",
    "document": "Документ",
    "unknown": "Невідомо",
}


def format_history_item(index: int, item: dict) -> str:
    """
    Форматує один запис історії для Telegram.
    """
    source_type = SOURCE_TYPE_LABELS.get(
        item.get("source_type"),
        item.get("source_type", "Невідомо")
    )

    source_name = item.get("source_name") or "Без назви"
    text_length = item.get("text_length", 0)
    chunks_count = item.get("chunks_count", 0)
    created_at = item.get("created_at") or "Невідомо"
    preview = item.get("text_preview") or "Без превʼю"

    return (
        f"{index}. <b>{source_type}</b> — {source_name}\n"
        f"   🕒 {created_at}\n"
        f"   🔠 Символів: {text_length}\n"
        f"   🎧 Частин: {chunks_count}\n"
        f"   <i>{preview}</i>"
    )


def build_history_text(items: list[dict]) -> str:
    """
    Формує текст історії користувача.
    """
    if not items:
        return EMPTY_HISTORY_TEXT

    parts = ["📚 <b>Останні оброблені матеріали:</b>\n"]

    for index, item in enumerate(items, start=1):
        parts.append(format_history_item(index, item))

    parts.append("\n/history_clear — очистити історію")

    return "\n\n".join(parts)