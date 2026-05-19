# Файл: services/document_history_service.py

import json
import logging

from aiogram import types

from database.db import (
    add_document_history,
    clear_user_document_history,
    count_user_document_history,
    delete_user_document,
    get_user_document_by_id,
    get_user_document_history,
    set_document_summary,
)

logger = logging.getLogger(__name__)

TEXT_PREVIEW_LENGTH = 300
DEFAULT_HISTORY_LIMIT = 5


def detect_message_source_type(message: types.Message) -> str:
    if message.document:
        return "document"

    if message.photo:
        return "photo"

    if message.text and ("http://" in message.text or "https://" in message.text):
        return "url"

    if message.text:
        return "text"

    return "unknown"


def get_message_source_name(message: types.Message) -> str:
    if message.document:
        return message.document.file_name or "Документ без назви"

    if message.photo:
        return "Фото з текстом"

    if message.text and ("http://" in message.text or "https://" in message.text):
        return "Посилання"

    if message.text:
        return "Текстове повідомлення"

    return "Невідоме джерело"


def build_text_preview(text: str) -> str:
    clean_text = " ".join(text.split())

    if len(clean_text) <= TEXT_PREVIEW_LENGTH:
        return clean_text

    return clean_text[:TEXT_PREVIEW_LENGTH - 3].strip() + "..."


def serialize_chunks(chunks: list[str]) -> str:
    return json.dumps(chunks, ensure_ascii=False)


def deserialize_chunks(chunks_json: str | None) -> list[str]:
    if not chunks_json:
        return []

    try:
        chunks = json.loads(chunks_json)
    except json.JSONDecodeError:
        logger.exception("DocumentHistory: не вдалося прочитати chunks_json")
        return []

    if not isinstance(chunks, list):
        return []

    return [str(chunk) for chunk in chunks if str(chunk).strip()]


async def save_document_history_from_message(
    user_id: int,
    message: types.Message,
    text: str,
    chunks: list[str]
) -> int | None:
    """
    Зберігає документ у каталог.

    Зберігаємо chunks, щоб документ можна було відкрити повторно.
    """
    if not text or not text.strip():
        return None

    if not chunks:
        return None

    source_type = detect_message_source_type(message)
    source_name = get_message_source_name(message)
    text_preview = build_text_preview(text)
    chunks_json = serialize_chunks(chunks)

    try:
        document_id = await add_document_history(
            user_id=user_id,
            source_type=source_type,
            source_name=source_name,
            text_preview=text_preview,
            text_length=len(text),
            chunks_count=len(chunks),
            chunks_json=chunks_json
        )

        logger.info(
            "DocumentCatalog: документ збережено user_id=%s document_id=%s source_type=%s length=%s chunks=%s",
            user_id,
            document_id,
            source_type,
            len(text),
            len(chunks)
        )

        return document_id

    except Exception:
        logger.exception(
            "DocumentCatalog: не вдалося зберегти документ user_id=%s",
            user_id
        )
        return None


async def get_recent_document_history(
    user_id: int,
    limit: int = DEFAULT_HISTORY_LIMIT,
    offset: int = 0,
) -> list[dict]:
    return await get_user_document_history(
        user_id=user_id,
        limit=limit,
        offset=offset,
    )


async def count_recent_document_history(user_id: int) -> int:
    return await count_user_document_history(user_id=user_id)


async def get_catalog_document_chunks(
    user_id: int,
    document_id: int
) -> tuple[dict | None, list[str]]:
    """
    Повертає документ і його chunks.
    """
    document = await get_user_document_by_id(
        user_id=user_id,
        document_id=document_id
    )

    if not document:
        return None, []

    chunks = deserialize_chunks(document.get("chunks_json"))

    return document, chunks


async def save_catalog_document_summary(
    user_id: int,
    document_id: int | None,
    summary_text: str,
) -> bool:
    if document_id is None:
        return False

    summary_text = summary_text.strip()

    if not summary_text:
        return False

    try:
        return await set_document_summary(
            user_id=user_id,
            document_id=document_id,
            summary_text=summary_text,
        )
    except Exception:
        logger.exception(
            "DocumentCatalog: не вдалося зберегти summary user_id=%s document_id=%s",
            user_id,
            document_id,
        )
        return False


async def delete_catalog_document(
    user_id: int,
    document_id: int
) -> None:
    await delete_user_document(
        user_id=user_id,
        document_id=document_id
    )


async def clear_document_history(user_id: int) -> None:
    await clear_user_document_history(user_id)
