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

SUMMARY_PREPARING_TEXT = "⏳ Готую короткий зміст за допомогою ШІ..."
SUMMARY_AUDIO_GENERATION_ERROR = "❌ Не вдалося згенерувати аудіо короткого змісту."
SUMMARY_GENERATION_ERROR = "❌ Сталася помилка генерації."
SUMMARY_CAPTION_TEXT = "📝 Короткий зміст від ШІ"

ACCOUNT_BLOCKED_TEXT = "🚫 Ваш акаунт заблоковано."
SESSION_NOT_FOUND_TEXT = "❌ Сесія читання не знайдена."
SESSION_NOT_FOUND_OR_FINISHED_TEXT = "❌ Сесія читання не знайдена або вже завершена."

WAIT_AUDIO_PROCESSING_TEXT = "⏳ Зачекайте, аудіо ще обробляється..."
WAIT_PROCESSING_TEXT = "⏳ Зачекайте, процеси ще виконуються..."

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


def build_part_caption(current_part: int, total_parts: int) -> str:
    return f"📄 Частина {current_part} з {total_parts}"


def build_large_text_split_text(parts_count: int) -> str:
    return f"📚 Текст великий. Його розбито на {parts_count} частин."


def build_text_was_limited_text(max_length: int) -> str:
    return (
        "⚠️ Текст дуже великий. "
        f"Для стабільної роботи буде озвучено перші {max_length} символів."
    )
