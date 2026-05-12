# Файл: services/content_extractor.py

import asyncio
import logging
import os
import tempfile

from aiogram import types

from services.file_processor import process_docx, process_pdf, process_txt
from services.ocr import extract_text_from_image
from services.parser import parse_article

logger = logging.getLogger(__name__)

MAX_DOCUMENT_SIZE_MB = 20
MAX_DOCUMENT_SIZE_BYTES = MAX_DOCUMENT_SIZE_MB * 1024 * 1024

SUPPORTED_FORMATS_ERROR = (
    "❌ Формат не підтримується. Надішліть PDF, DOCX, TXT або фото."
)


def _safe_remove_file(file_path: str | None) -> None:
    """
    Безпечно видаляє тимчасовий файл.
    """
    if not file_path:
        return

    if not os.path.exists(file_path):
        return

    try:
        os.remove(file_path)
        logger.debug("ContentExtractor: тимчасовий файл видалено: %s", file_path)
    except OSError:
        logger.exception(
            "ContentExtractor: не вдалося видалити тимчасовий файл: %s",
            file_path
        )


async def _safe_edit_status(
    status_msg: types.Message | None,
    text: str
) -> None:
    """
    Безпечно оновлює службове повідомлення статусу.
    """
    if status_msg is None:
        return

    try:
        await status_msg.edit_text(text)
    except Exception:
        logger.exception(
            "ContentExtractor: не вдалося оновити службове повідомлення"
        )


def _contains_url(text: str) -> bool:
    """
    Перевіряє, чи містить текст URL.

    Логіка збережена такою ж, як була в handlers/messages.py.
    """
    return "http://" in text or "https://" in text


def _get_document_filename(message: types.Message) -> str:
    """
    Повертає назву документа в нижньому регістрі.

    Якщо Telegram не передав file_name, повертає порожній рядок.
    """
    if not message.document:
        return ""

    return (message.document.file_name or "").lower().strip()


def _is_document_too_large(message: types.Message) -> bool:
    """
    Перевіряє, чи перевищує документ дозволений розмір.
    """
    if not message.document:
        return False

    file_size = message.document.file_size

    return bool(file_size and file_size > MAX_DOCUMENT_SIZE_BYTES)


async def _download_to_temp_file(
    message: types.Message,
    telegram_file,
    suffix: str = ""
) -> str:
    """
    Завантажує Telegram-файл у тимчасовий файл і повертає шлях до нього.
    """
    downloaded_file = await message.bot.download(telegram_file)

    if downloaded_file is None:
        raise RuntimeError("Telegram не повернув файл під час завантаження.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(downloaded_file.read())
        return tmp.name


async def _extract_from_text_message(message: types.Message) -> str:
    """
    Витягує текст зі звичайного текстового повідомлення.

    Якщо повідомлення містить URL, пробує витягнути статтю через parser.
    """
    text = message.text or ""

    if _contains_url(text):
        return await parse_article(text)

    return text


async def _extract_from_photo(
    message: types.Message,
    status_msg: types.Message | None
) -> str:
    """
    Завантажує фото, запускає OCR і повертає розпізнаний текст.
    """
    await _safe_edit_status(status_msg, "👁 Розпізнаю текст на фотографії...")

    if not message.photo:
        return "❌ Не вдалося отримати фото."

    photo = message.photo[-1]
    tmp_path = None

    try:
        tmp_path = await _download_to_temp_file(
            message=message,
            telegram_file=photo,
            suffix=".jpg"
        )

        return await extract_text_from_image(tmp_path)

    except Exception:
        logger.exception(
            "ContentExtractor: помилка OCR фото для user_id=%s",
            message.from_user.id if message.from_user else None
        )
        return "❌ Сталася помилка під час аналізу фото."

    finally:
        _safe_remove_file(tmp_path)


async def _extract_from_document(
    message: types.Message,
    status_msg: types.Message | None
) -> str:
    """
    Завантажує документ і витягує з нього текст залежно від формату.
    """
    if not message.document:
        return "❌ Документ не знайдено."

    if _is_document_too_large(message):
        return (
            f"❌ Файл занадто великий. "
            f"Максимальний розмір документа — {MAX_DOCUMENT_SIZE_MB} МБ."
        )

    filename = _get_document_filename(message)
    tmp_path = None

    try:
        tmp_path = await _download_to_temp_file(
            message=message,
            telegram_file=message.document
        )

        if filename.endswith(".docx"):
            return await asyncio.to_thread(process_docx, tmp_path)

        if filename.endswith(".pdf"):
            return await asyncio.to_thread(process_pdf, tmp_path)

        if filename.endswith(".txt"):
            return await asyncio.to_thread(process_txt, tmp_path)

        if filename.endswith((".jpg", ".jpeg", ".png")):
            await _safe_edit_status(
                status_msg,
                "👁 Розпізнаю зображення з документа..."
            )
            return await extract_text_from_image(tmp_path)

        return SUPPORTED_FORMATS_ERROR

    except Exception:
        logger.exception(
            "ContentExtractor: помилка читання документа для user_id=%s filename=%s",
            message.from_user.id if message.from_user else None,
            filename
        )
        return "❌ Помилка читання файлу."

    finally:
        _safe_remove_file(tmp_path)


async def extract_text_from_message(
    message: types.Message,
    status_msg: types.Message | None = None
) -> str:
    """
    Головна функція витягування тексту з Telegram-повідомлення.

    Підтримує:
    - звичайний текст;
    - URL;
    - фото;
    - PDF;
    - DOCX;
    - TXT;
    - JPG/JPEG/PNG як документ.

    Повертає:
    - витягнутий текст;
    - або текст помилки, який починається з ❌.
    """
    if message.text:
        return await _extract_from_text_message(message)

    if message.photo:
        return await _extract_from_photo(message, status_msg)

    if message.document:
        return await _extract_from_document(message, status_msg)

    return "❌ Не вдалося отримати текст."