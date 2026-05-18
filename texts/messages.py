# Файл: texts/messages.py

UNKNOWN_COMMAND_TEXT = (
    "❌ Невідома команда.\n\n"
    "Доступні команди:\n"
    "/start — почати роботу\n"
    "/settings — налаштування голосу"
)

RATE_LIMIT_TEXT = (
    "⏳ Ви надсилаєте запити занадто швидко. "
    "Будь ласка, зачекайте кілька секунд і спробуйте ще раз."
)

GENERIC_INTERNAL_ERROR_TEXT = (
    "❌ Сталася непередбачена помилка. "
    "Спробуйте ще раз трохи пізніше."
)

OUTDATED_READING_BUTTON_TEXT = (
    "❌ Ця кнопка належить до старої сесії читання. "
    "Надішліть документ або текст ще раз."
)

ANALYZING_MATERIAL_TEXT = "⏳ Аналізую матеріал..."

GENERIC_TEXT_EXTRACT_ERROR = "❌ Не вдалося отримати текст."
TEXT_SPLIT_ERROR = "❌ Не вдалося розбити текст."

UNSUPPORTED_MESSAGE_TEXT = (
    "ℹ️ Я можу обробити текст, посилання, PDF, DOCX, TXT або фотографію. "
    "Стікери, GIF, голосові та інші типи повідомлень не обробляються."
)

BACKGROUND_GENERATION_ERROR = "❌ Помилка фонової генерації."
CHUNK_AUDIO_GENERATION_ERROR = "❌ Не вдалося згенерувати аудіо для цієї частини."
AUDIO_QUEUE_FULL_TEXT = (
    "⏳ Черга озвучки зараз заповнена. "
    "Будь ласка, спробуйте ще раз трохи пізніше."
)

SUMMARY_PREPARING_TEXT = "⏳ Готую короткий зміст за допомогою ШІ..."
SUMMARY_AUDIO_GENERATION_ERROR = "❌ Не вдалося згенерувати аудіо короткого змісту."
SUMMARY_GENERATION_ERROR = "❌ Сталася помилка генерації."
SUMMARY_CAPTION_TEXT = "📝 Короткий зміст від ШІ"

ACCOUNT_BLOCKED_TEXT = "🚫 Ваш акаунт заблоковано."
SESSION_NOT_FOUND_TEXT = "❌ Сесія читання не знайдена."
SESSION_NOT_FOUND_OR_FINISHED_TEXT = "❌ Сесія читання не знайдена або вже завершена."

WAIT_AUDIO_PROCESSING_TEXT = "⏳ Зачекайте, аудіо ще обробляється..."
WAIT_PROCESSING_TEXT = "⏳ Зачекайте, процеси ще виконуються..."
WAIT_CURRENT_AUDIO_REQUEST_TEXT = (
    "⏳ Ваш попередній матеріал ще очікує або генерується. "
    "Дочекайтесь аудіо або натисніть «Закінчити», перш ніж надсилати новий."
)

READING_STOPPED_ALERT_TEXT = "🛑 Читання зупинено."
READING_STOPPED_MESSAGE_TEXT = "🛑 Ви зупинили прослуховування документа."

ALL_PARTS_SENT_TEXT = (
    "✅ Всі частини надіслано. "
    "Ви можете прослухати короткий зміст або завершити роботу з файлом."
)


def build_loading_chunk_text(current_part: int, total_parts: int) -> str:
    return f"⏳ Довантажую частину {current_part} з {total_parts}..."


def build_generating_chunk_text(current_part: int, total_parts: int) -> str:
    return f"⏳ Генерую частину {current_part} з {total_parts}..."


def build_audio_generation_queued_text(
    current_part: int,
    total_parts: int,
    queue_position: int,
) -> str:
    return (
        f"⏳ Додав частину {current_part} з {total_parts} у чергу озвучки. "
        f"Позиція: {queue_position}."
    )


def build_generating_audio_progress_text(
    *,
    current_part: int,
    total_parts: int,
    completed_audio_chunks: int,
    total_audio_chunks: int,
    provider: str,
    cache_hit: bool,
) -> str:
    cache_text = " з кешу" if cache_hit else ""

    return (
        f"⏳ Генерую частину {current_part} з {total_parts}: "
        f"аудіо {completed_audio_chunks}/{total_audio_chunks} "
        f"через {provider}{cache_text}..."
    )


def build_part_caption(current_part: int, total_parts: int) -> str:
    return f"📄 Частина {current_part} з {total_parts}"


def build_part_audio_caption(
    *,
    current_part: int,
    total_parts: int,
    current_audio: int,
    total_audio: int,
) -> str:
    part_caption = build_part_caption(current_part, total_parts)

    if total_audio <= 1:
        return part_caption

    return f"{part_caption} · аудіо {current_audio} з {total_audio}"


def build_large_text_split_text(parts_count: int) -> str:
    return f"📚 Текст великий. Його розбито на {parts_count} частин."


def build_text_was_limited_text(max_length: int) -> str:
    return (
        "⚠️ Текст дуже великий. "
        f"Для стабільної роботи буде озвучено перші {max_length} символів."
    )


EXPORT_AUDIO_ACCESS_DENIED_TEXT = (
    "🔒 Об'єднання в один файл доступне тільки для Ліміт+."
)
EXPORT_AUDIO_CONCATENATING_TEXT = "⏳ Об'єдную аудіо в один файл..."
EXPORT_AUDIO_GENERATION_ERROR = (
    "❌ Не вдалося зібрати повну озвучку в один файл."
)
EXPORT_AUDIO_CAPTION_TEXT = "🎧 Повна озвучка одним файлом"


def build_export_audio_queued_text(
    total_parts: int,
    queue_position: int,
) -> str:
    return (
        f"⏳ Додав повну озвучку з {total_parts} частин у чергу. "
        f"Позиція: {queue_position}."
    )


def build_export_audio_part_text(current_part: int, total_parts: int) -> str:
    return (
        f"⏳ Готую повну озвучку: частина {current_part} з {total_parts}..."
    )


def build_export_audio_progress_text(
    *,
    current_part: int,
    total_parts: int,
    completed_audio_chunks: int,
    total_audio_chunks: int,
    provider: str,
    cache_hit: bool,
) -> str:
    cache_text = " з кешу" if cache_hit else ""

    return (
        f"⏳ Готую повну озвучку: частина {current_part} з {total_parts}, "
        f"аудіо {completed_audio_chunks}/{total_audio_chunks} "
        f"через {provider}{cache_text}..."
    )


def build_export_audio_too_large_text(
    *,
    file_size_mb: float,
    max_size_mb: int,
) -> str:
    return (
        "⚠️ Повний аудіофайл завеликий для Telegram voice: "
        f"{file_size_mb:.1f} MB з ліміту {max_size_mb} MB. "
        "Залишаю озвучку частинами."
    )
