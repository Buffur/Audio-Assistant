# Файл: texts/messages.py

UNKNOWN_COMMAND_TEXT = (
    "❌ Невідома команда.\n\n"
    "Доступні команди:\n"
    "/start — почати роботу\n"
    "/help — показати довідку\n"
    "/settings — налаштувати голос і швидкість\n"
    "/catalog — каталог документів\n"
    "/usage — показати статистику використання"
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
    "Ця кнопка від попереднього документа. "
    "Актуальні кнопки знаходяться під останнім аудіо. "
    "Щоб повернутись до старого матеріалу, відкрийте його з /catalog."
)

ANALYZING_MATERIAL_TEXT = "⏳ Аналізую матеріал..."
SPLITTING_TEXT_STATUS = "⏳ Розбиваю текст на частини..."
PREPARING_FIRST_AUDIO_TEXT = "⏳ Готую першу частину аудіо..."

GENERIC_TEXT_EXTRACT_ERROR = (
    "❌ Не вдалося отримати текст з цього матеріалу. "
    "Спробуйте PDF/DOCX/TXT з виділюваним текстом або надішліть чітке фото."
)
TEXT_SPLIT_ERROR = (
    "❌ Не вдалося підготувати текст до озвучення. "
    "Спробуйте надіслати менший фрагмент."
)

UNSUPPORTED_MESSAGE_TEXT = (
    "ℹ️ Я можу обробити текст, посилання, PDF, DOCX, TXT або фотографію. "
    "Стікери, GIF, голосові та інші типи повідомлень не обробляються."
)
UNSUPPORTED_MESSAGE_REPEAT_TEXT = (
    "Цей тип повідомлення я не обробляю. "
    "Надішліть текст, PDF/DOCX/TXT, фото з текстом або посилання."
)

BACKGROUND_GENERATION_ERROR = (
    "❌ Не вдалося озвучити цю частину. "
    "Спробуйте натиснути «Слухати далі» ще раз. "
    "Якщо помилка повториться, надішліть менший фрагмент тексту."
)
CHUNK_AUDIO_GENERATION_ERROR = (
    "❌ Не вдалося згенерувати аудіо для цієї частини. "
    "Спробуйте повторити дію трохи пізніше."
)
AUDIO_QUEUE_FULL_TEXT = (
    "⏳ Зараз занадто багато задач озвучки, тому цю дію не поставлено в чергу. "
    "Спробуйте ще раз через 1-2 хвилини. Поточний документ не втрачено."
)

SUMMARY_PREPARING_TEXT = "⏳ Готую короткий зміст за допомогою ШІ..."
SUMMARY_VOICE_PREPARING_TEXT = "⏳ Готую озвучку короткого змісту..."
SUMMARY_AUDIO_GENERATION_ERROR = "❌ Не вдалося згенерувати аудіо короткого змісту."
SUMMARY_GENERATION_ERROR = (
    "❌ Не вдалося створити короткий зміст. "
    "Спробуйте ще раз трохи пізніше."
)
SUMMARY_CAPTION_TEXT = "📝 Короткий зміст від ШІ"
SUMMARY_ALREADY_READY_TEXT = (
    "Короткий зміст уже готовий."
)
SUMMARY_ALREADY_SENT_TEXT = (
    "Короткий зміст уже готовий."
)
SUMMARY_CACHED_TEXT_HEADER = "📝 Короткий зміст:"

ACCOUNT_BLOCKED_TEXT = "🚫 Ваш акаунт заблоковано."
SESSION_NOT_FOUND_TEXT = (
    "❌ Це читання вже завершене або було замінене новим документом. "
    "Щоб продовжити, відкрийте матеріал з /catalog або надішліть його ще раз."
)
SESSION_NOT_FOUND_OR_FINISHED_TEXT = (
    "❌ Це читання вже завершене. "
    "Щоб продовжити, відкрийте матеріал з /catalog або надішліть його ще раз."
)

WAIT_AUDIO_PROCESSING_TEXT = "⏳ Зачекайте, аудіо ще обробляється..."
WAIT_PROCESSING_TEXT = "⏳ Зачекайте, процеси ще виконуються..."
WAIT_CURRENT_AUDIO_REQUEST_TEXT = (
    "⏳ Ваш попередній матеріал ще очікує або генерується. "
    "Дочекайтесь аудіо або натисніть «Закінчити», перш ніж надсилати новий."
)

READING_STOPPED_ALERT_TEXT = "🛑 Читання зупинено."
READING_STOPPED_MESSAGE_TEXT = (
    "🛑 Читання зупинено. "
    "Якщо потрібно повернутись до документа, відкрийте його з /catalog."
)

ALL_PARTS_SENT_TEXT = (
    "✅ Всі частини надіслано. "
    "Ви можете прослухати короткий зміст або завершити роботу з файлом."
)
ALL_PARTS_SENT_AFTER_SUMMARY_TEXT = (
    "✅ Всі частини надіслано. "
    "Короткий зміст файлу вже створено, можете завершити роботу з файлом."
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
        f"⏳ Частина {current_part} з {total_parts} у черзі озвучки.\n"
        f"Позиція в черзі: {queue_position}.\n"
        "Нічого натискати не потрібно — я надішлю аудіо тут, щойно воно буде готове. "
        "Якщо цей документ більше не потрібен, натисніть «Зупинити читання»."
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
    cache_text = " Готовий фрагмент знайдено в кеші." if cache_hit else ""

    return (
        f"⏳ Генерую частину {current_part} з {total_parts}: "
        f"аудіо {completed_audio_chunks}/{total_audio_chunks}..."
        f"{cache_text}"
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
    return (
        f"📚 Текст великий, я розділив його на {parts_count} частин.\n"
        "Зараз готую першу частину. Після прослуховування натискайте "
        "«Слухати далі»."
    )


def build_text_was_limited_text(max_length: int) -> str:
    return (
        "⚠️ Текст дуже великий. "
        f"Для стабільної роботи буде озвучено перші {max_length} символів."
    )


EXPORT_AUDIO_ACCESS_DENIED_TEXT = (
    "🔒 Один аудіофайл доступний тільки для Ліміт+. "
    "Звичайне прослуховування частинами доступне без Ліміт+."
)
EXPORT_AUDIO_CONCATENATING_TEXT = "⏳ Об'єдную аудіо в один файл..."
EXPORT_AUDIO_GENERATION_ERROR = (
    "❌ Не вдалося зібрати повну озвучку в один файл. "
    "Озвучку частинами можна продовжити з поточного документа."
)
EXPORT_AUDIO_CAPTION_TEXT = "🎧 Повна озвучка одним файлом"


def build_export_audio_queued_text(
    total_parts: int,
    queue_position: int,
) -> str:
    return (
        f"⏳ Один аудіофайл з {total_parts} частин у черзі.\n"
        f"Позиція в черзі: {queue_position}.\n"
        "Нічого натискати не потрібно — я надішлю файл тут, щойно він буде готовий. "
        "Якщо цей документ більше не потрібен, натисніть «Зупинити читання»."
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
    cache_text = " Готовий фрагмент знайдено в кеші." if cache_hit else ""

    return (
        f"⏳ Готую повну озвучку: частина {current_part} з {total_parts}, "
        f"аудіо {completed_audio_chunks}/{total_audio_chunks}..."
        f"{cache_text}"
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
