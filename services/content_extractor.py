# Файл: services/content_extractor.py

import logging
import os
import tempfile
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

from aiogram import types

from config import (
    DOCX_EXTRACTION_TIMEOUT_SECONDS,
    PDF_EXTRACTION_TIMEOUT_SECONDS,
    TELEGRAM_FILE_DOWNLOAD_TIMEOUT_SECONDS,
    TXT_EXTRACTION_TIMEOUT_SECONDS,
)
from services.file_processor import process_docx, process_pdf, process_txt
from services.operation_timeouts import (
    OperationTimeoutError,
    run_sync_with_timeout,
    run_with_timeout,
)
from services.ocr import extract_text_from_image
from services.parser import extract_first_url, parse_article

logger = logging.getLogger(__name__)

MAX_DOCUMENT_SIZE_MB = 20
MAX_DOCUMENT_SIZE_BYTES = MAX_DOCUMENT_SIZE_MB * 1024 * 1024

SUPPORTED_FORMATS_ERROR = (
    "❌ Формат не підтримується.\n"
    "Надішліть PDF, DOCX, TXT, фото з текстом або посилання на статтю."
)

FILE_TOO_LARGE_ERROR = (
    f"❌ Файл занадто великий.\n"
    f"Максимальний розмір документа — {MAX_DOCUMENT_SIZE_MB} МБ."
)
FILE_PROCESSING_TIMEOUT_ERROR = (
    "❌ Обробка файлу зайняла занадто багато часу. "
    "Спробуйте менший файл або документ із простішою структурою."
)

DOWNLOADING_FILE_STATUS_TEXT = "⏳ Завантажую файл..."
PARSING_URL_STATUS_TEXT = "⏳ Завантажую сторінку та шукаю основний текст..."
OCR_PHOTO_STATUS_TEXT = "⏳ Розпізнаю текст на фотографії..."
OCR_DOCUMENT_IMAGE_STATUS_TEXT = "⏳ Розпізнаю текст на зображенні..."
EXTRACTING_PDF_STATUS_TEXT = "⏳ Витягую текст із PDF..."
EXTRACTING_DOCX_STATUS_TEXT = "⏳ Витягую текст із DOCX..."
EXTRACTING_TXT_STATUS_TEXT = "⏳ Читаю TXT файл..."

DOCUMENT_KIND_PDF = "pdf"
DOCUMENT_KIND_DOCX = "docx"
DOCUMENT_KIND_TXT = "txt"
DOCUMENT_KIND_IMAGE = "image"

SUPPORTED_DOCUMENT_KINDS = {
    DOCUMENT_KIND_PDF,
    DOCUMENT_KIND_DOCX,
    DOCUMENT_KIND_TXT,
    DOCUMENT_KIND_IMAGE,
}

SUPPORTED_EXTENSIONS = {
    ".pdf": DOCUMENT_KIND_PDF,
    ".docx": DOCUMENT_KIND_DOCX,
    ".txt": DOCUMENT_KIND_TXT,
    ".jpg": DOCUMENT_KIND_IMAGE,
    ".jpeg": DOCUMENT_KIND_IMAGE,
    ".png": DOCUMENT_KIND_IMAGE,
}

SUPPORTED_MIME_TYPES = {
    "application/pdf": DOCUMENT_KIND_PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        DOCUMENT_KIND_DOCX
    ),
    "text/plain": DOCUMENT_KIND_TXT,
    "image/jpeg": DOCUMENT_KIND_IMAGE,
    "image/png": DOCUMENT_KIND_IMAGE,
}

ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
DOCX_MAIN_DOCUMENT_PATH = "word/document.xml"

DOCUMENT_KIND_SUFFIXES = {
    DOCUMENT_KIND_PDF: ".pdf",
    DOCUMENT_KIND_DOCX: ".docx",
    DOCUMENT_KIND_TXT: ".txt",
    DOCUMENT_KIND_IMAGE: ".jpg",
}

DOCUMENT_EXTRACTION_STATUS_TEXTS = {
    DOCUMENT_KIND_PDF: EXTRACTING_PDF_STATUS_TEXT,
    DOCUMENT_KIND_DOCX: EXTRACTING_DOCX_STATUS_TEXT,
    DOCUMENT_KIND_TXT: EXTRACTING_TXT_STATUS_TEXT,
}


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
        logger.debug(
            "ContentExtractor: тимчасовий файл видалено: %s",
            file_path,
        )
    except OSError:
        logger.exception(
            "ContentExtractor: не вдалося видалити тимчасовий файл: %s",
            file_path,
        )


async def _safe_edit_status(
    status_msg: types.Message | None,
    text: str,
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


def _get_document_filename(message: types.Message) -> str:
    """
    Повертає назву документа в нижньому регістрі.
    Якщо Telegram не передав file_name, повертає порожній рядок.
    """
    if not message.document:
        return ""

    return (message.document.file_name or "").lower().strip()


def _get_document_extension(filename: str) -> str:
    """
    Повертає розширення файлу в нижньому регістрі.
    """
    if not filename:
        return ""

    return Path(filename).suffix.lower()


def _get_document_mime_type(message: types.Message) -> str:
    """
    Повертає MIME-тип документа, якщо Telegram його передав.
    """
    if not message.document:
        return ""

    return (message.document.mime_type or "").lower().strip()


def is_supported_document_metadata(document: object | None) -> bool:
    if document is None:
        return False

    filename = str(getattr(document, "file_name", "") or "").lower().strip()
    mime_type = str(getattr(document, "mime_type", "") or "").lower().strip()
    extension = _get_document_extension(filename)

    if extension:
        return extension in SUPPORTED_EXTENSIONS

    return mime_type in SUPPORTED_MIME_TYPES


def _is_document_too_large(message: types.Message) -> bool:
    """
    Перевіряє, чи перевищує документ дозволений розмір за metadata Telegram.
    """
    if not message.document:
        return False

    file_size = message.document.file_size
    return bool(file_size and file_size > MAX_DOCUMENT_SIZE_BYTES)


def _is_downloaded_file_too_large(file_bytes: bytes) -> bool:
    """
    Перевіряє фактичний розмір завантаженого файлу.
    """
    return len(file_bytes) > MAX_DOCUMENT_SIZE_BYTES


def _is_zip_container(file_bytes: bytes) -> bool:
    return file_bytes.startswith(ZIP_SIGNATURES)


def _is_docx_container(file_bytes: bytes) -> bool:
    if not _is_zip_container(file_bytes):
        return False

    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
            return DOCX_MAIN_DOCUMENT_PATH in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _detect_kind_by_magic_bytes(file_bytes: bytes) -> str | None:
    """
    Визначає тип файлу за початковими байтами.

    Це не повна антивірусна перевірка, але вона допомагає не довіряти
    лише назві файлу.
    """
    if file_bytes.startswith(b"%PDF-"):
        return DOCUMENT_KIND_PDF

    if _is_docx_container(file_bytes):
        return DOCUMENT_KIND_DOCX

    if file_bytes.startswith(b"\xff\xd8\xff"):
        return DOCUMENT_KIND_IMAGE

    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return DOCUMENT_KIND_IMAGE

    return None


def _looks_like_text_file(file_bytes: bytes) -> bool:
    """
    TXT не має стабільної сигнатури, тому перевіряємо,
    чи файл схожий на текстовий.
    """
    if not file_bytes:
        return False

    sample = file_bytes[:4096]

    if b"\x00" in sample:
        return False

    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass

    try:
        sample.decode("cp1251")
        return True
    except UnicodeDecodeError:
        return False


def _detect_document_kind(
    *,
    filename: str,
    mime_type: str,
    file_bytes: bytes,
) -> str | None:
    """
    Визначає тип документа за розширенням, MIME-типом і magic bytes.

    Пріоритет:
    1. magic bytes;
    2. MIME type;
    3. extension;
    4. fallback-перевірка для TXT.
    """
    extension = _get_document_extension(filename)

    kind_by_magic = _detect_kind_by_magic_bytes(file_bytes)
    if kind_by_magic in SUPPORTED_DOCUMENT_KINDS:
        return kind_by_magic

    if _is_zip_container(file_bytes):
        return None

    if extension and extension not in SUPPORTED_EXTENSIONS:
        return None

    kind_by_mime = SUPPORTED_MIME_TYPES.get(mime_type)
    if kind_by_mime in SUPPORTED_DOCUMENT_KINDS:
        return kind_by_mime

    kind_by_extension = SUPPORTED_EXTENSIONS.get(extension)
    if kind_by_extension in SUPPORTED_DOCUMENT_KINDS:
        if kind_by_extension == DOCUMENT_KIND_TXT and not _looks_like_text_file(
            file_bytes
        ):
            return None

        return kind_by_extension

    return None


def _get_suffix_for_document_kind(kind: str) -> str:
    return DOCUMENT_KIND_SUFFIXES.get(kind, "")


async def _download_to_temp_file(
    message: types.Message,
    telegram_file,
    suffix: str = "",
) -> tuple[str, bytes]:
    """
    Завантажує Telegram-файл у тимчасовий файл і повертає шлях та bytes.
    """
    downloaded_file = await run_with_timeout(
        message.bot.download(telegram_file),
        operation="telegram_file_download",
        timeout_seconds=TELEGRAM_FILE_DOWNLOAD_TIMEOUT_SECONDS,
    )

    if downloaded_file is None:
        raise RuntimeError("Telegram не повернув файл під час завантаження.")

    file_bytes = await run_sync_with_timeout(
        downloaded_file.read,
        operation="telegram_file_read",
        timeout_seconds=TELEGRAM_FILE_DOWNLOAD_TIMEOUT_SECONDS,
    )

    if _is_downloaded_file_too_large(file_bytes):
        raise ValueError(FILE_TOO_LARGE_ERROR)

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        return tmp.name, file_bytes


async def _run_document_processor(
    processor: Callable[[str], str],
    file_path: str,
    *,
    document_kind: str,
) -> str:
    timeout_seconds_by_kind = {
        DOCUMENT_KIND_DOCX: DOCX_EXTRACTION_TIMEOUT_SECONDS,
        DOCUMENT_KIND_PDF: PDF_EXTRACTION_TIMEOUT_SECONDS,
        DOCUMENT_KIND_TXT: TXT_EXTRACTION_TIMEOUT_SECONDS,
    }
    timeout_seconds = timeout_seconds_by_kind[document_kind]

    return await run_sync_with_timeout(
        processor,
        file_path,
        operation=f"{document_kind}_text_extraction",
        timeout_seconds=timeout_seconds,
    )


async def _extract_from_text_message(
    message: types.Message,
    status_msg: types.Message | None,
) -> str:
    """
    Витягує текст зі звичайного текстового повідомлення.

    Якщо повідомлення містить URL, пробує витягнути статтю через parser.
    """
    text = message.text or ""
    url = extract_first_url(text)

    if url:
        await _safe_edit_status(status_msg, PARSING_URL_STATUS_TEXT)
        return await parse_article(url)

    return text


async def _extract_from_photo(
    message: types.Message,
    status_msg: types.Message | None,
) -> str:
    """
    Завантажує фото, запускає OCR і повертає розпізнаний текст.
    """
    await _safe_edit_status(status_msg, OCR_PHOTO_STATUS_TEXT)

    if not message.photo:
        return "❌ Не вдалося отримати фото."

    photo = message.photo[-1]
    tmp_path = None

    try:
        tmp_path, _ = await _download_to_temp_file(
            message=message,
            telegram_file=photo,
            suffix=".jpg",
        )

        return await extract_text_from_image(tmp_path)

    except OperationTimeoutError as error:
        logger.warning(
            "ContentExtractor: timeout during photo processing user_id=%s "
            "operation=%s timeout=%s",
            message.from_user.id if message.from_user else None,
            error.operation,
            error.timeout_seconds,
        )
        return FILE_PROCESSING_TIMEOUT_ERROR

    except ValueError as error:
        error_text = str(error)
        logger.warning(
            "ContentExtractor: фото не оброблено для user_id=%s: %s",
            message.from_user.id if message.from_user else None,
            error_text,
        )
        return error_text

    except Exception:
        logger.exception(
            "ContentExtractor: помилка OCR фото для user_id=%s",
            message.from_user.id if message.from_user else None,
        )
        return "❌ Сталася помилка під час аналізу фото."

    finally:
        _safe_remove_file(tmp_path)


async def _extract_from_document(
    message: types.Message,
    status_msg: types.Message | None,
) -> str:
    """
    Завантажує документ і витягує з нього текст залежно від формату.
    """
    if not message.document:
        return "❌ Документ не знайдено."

    if _is_document_too_large(message):
        return FILE_TOO_LARGE_ERROR

    filename = _get_document_filename(message)
    mime_type = _get_document_mime_type(message)

    tmp_path = None

    try:
        await _safe_edit_status(status_msg, DOWNLOADING_FILE_STATUS_TEXT)
        tmp_path, file_bytes = await _download_to_temp_file(
            message=message,
            telegram_file=message.document,
        )

        document_kind = _detect_document_kind(
            filename=filename,
            mime_type=mime_type,
            file_bytes=file_bytes,
        )

        if document_kind is None:
            logger.warning(
                "ContentExtractor: непідтримуваний файл. "
                "user_id=%s filename=%s mime_type=%s",
                message.from_user.id if message.from_user else None,
                filename,
                mime_type,
            )
            return SUPPORTED_FORMATS_ERROR

        suffix = _get_suffix_for_document_kind(document_kind)

        if suffix and not tmp_path.endswith(suffix):
            renamed_tmp_path = f"{tmp_path}{suffix}"
            os.replace(tmp_path, renamed_tmp_path)
            tmp_path = renamed_tmp_path

        status_text = DOCUMENT_EXTRACTION_STATUS_TEXTS.get(document_kind)
        if status_text:
            await _safe_edit_status(status_msg, status_text)

        if document_kind == DOCUMENT_KIND_DOCX:
            return await _run_document_processor(
                process_docx,
                tmp_path,
                document_kind=DOCUMENT_KIND_DOCX,
            )

        if document_kind == DOCUMENT_KIND_PDF:
            return await _run_document_processor(
                process_pdf,
                tmp_path,
                document_kind=DOCUMENT_KIND_PDF,
            )

        if document_kind == DOCUMENT_KIND_TXT:
            return await _run_document_processor(
                process_txt,
                tmp_path,
                document_kind=DOCUMENT_KIND_TXT,
            )

        if document_kind == DOCUMENT_KIND_IMAGE:
            await _safe_edit_status(
                status_msg,
                OCR_DOCUMENT_IMAGE_STATUS_TEXT,
            )
            return await extract_text_from_image(tmp_path)

        return SUPPORTED_FORMATS_ERROR

    except OperationTimeoutError as error:
        logger.warning(
            "ContentExtractor: timeout during document processing user_id=%s "
            "filename=%s mime_type=%s operation=%s timeout=%s",
            message.from_user.id if message.from_user else None,
            filename,
            mime_type,
            error.operation,
            error.timeout_seconds,
        )
        return FILE_PROCESSING_TIMEOUT_ERROR

    except ValueError as error:
        error_text = str(error)
        logger.warning(
            "ContentExtractor: документ не оброблено для user_id=%s "
            "filename=%s mime_type=%s: %s",
            message.from_user.id if message.from_user else None,
            filename,
            mime_type,
            error_text,
        )
        return error_text

    except Exception:
        logger.exception(
            "ContentExtractor: помилка читання документа для user_id=%s "
            "filename=%s mime_type=%s",
            message.from_user.id if message.from_user else None,
            filename,
            mime_type,
        )
        return "❌ Помилка читання файлу."

    finally:
        _safe_remove_file(tmp_path)


async def extract_text_from_message(
    message: types.Message,
    status_msg: types.Message | None = None,
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
        return await _extract_from_text_message(message, status_msg)

    if message.photo:
        return await _extract_from_photo(message, status_msg)

    if message.document:
        return await _extract_from_document(message, status_msg)

    return "❌ Не вдалося отримати текст."
