# Файл: services/document_history_service.py

import hashlib
import json
import logging
from dataclasses import dataclass

from aiogram import types

from database.db import (
    add_document_history,
    clear_user_document_history,
    count_user_document_history,
    delete_user_document,
    get_latest_document_summary_by_chunks_json,
    get_latest_document_summary_by_content_hash,
    get_user_document_by_id,
    get_user_document_history,
    set_document_summary,
    set_document_summary_audio,
)

logger = logging.getLogger(__name__)

TEXT_PREVIEW_LENGTH = 300
DEFAULT_HISTORY_LIMIT = 5
SUMMARY_CACHE_VERSION = "summary-cache-v1"


@dataclass(frozen=True)
class CachedDocumentSummary:
    summary_text: str
    summary_voice_file_ids: list[str]
    summary_voice_voice: str | None
    summary_voice_rate: str | None
    summary_voice_provider: str | None


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


def normalize_text_for_content_cache(text: str) -> str:
    return " ".join(text.split()).strip()


def build_content_hash(text: str) -> str | None:
    normalized_text = normalize_text_for_content_cache(text)

    if not normalized_text:
        return None

    raw_value = f"{SUMMARY_CACHE_VERSION}\n{normalized_text}"

    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


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


def serialize_voice_file_ids(file_ids: list[str]) -> str:
    return json.dumps(file_ids, ensure_ascii=False)


def deserialize_voice_file_ids(file_ids_json: str | None) -> list[str]:
    if not file_ids_json:
        return []

    try:
        file_ids = json.loads(file_ids_json)
    except json.JSONDecodeError:
        logger.exception(
            "DocumentHistory: не вдалося прочитати summary voice file_ids"
        )
        return []

    if not isinstance(file_ids, list):
        return []

    return [str(file_id) for file_id in file_ids if str(file_id).strip()]


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
    content_hash = build_content_hash(text)

    try:
        document_id = await add_document_history(
            user_id=user_id,
            source_type=source_type,
            source_name=source_name,
            text_preview=text_preview,
            text_length=len(text),
            chunks_count=len(chunks),
            chunks_json=chunks_json,
            content_hash=content_hash,
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


async def get_cached_summary_for_text(
    user_id: int,
    text: str,
    chunks: list[str] | None = None,
    exclude_document_id: int | None = None,
) -> CachedDocumentSummary | None:
    content_hash = build_content_hash(text)

    if not content_hash and not chunks:
        return None

    try:
        cached = None

        if content_hash:
            cached = await get_latest_document_summary_by_content_hash(
                user_id=user_id,
                content_hash=content_hash,
                exclude_document_id=exclude_document_id,
            )

        if cached is None and chunks:
            cached = await get_latest_document_summary_by_chunks_json(
                user_id=user_id,
                chunks_json=serialize_chunks(chunks),
                exclude_document_id=exclude_document_id,
            )
    except Exception:
        logger.exception(
            "DocumentCatalog: не вдалося прочитати cached summary user_id=%s",
            user_id,
        )
        return None

    if not cached:
        return None

    summary_text = str(cached.get("summary_text") or "").strip()

    if not summary_text:
        return None

    return CachedDocumentSummary(
        summary_text=summary_text,
        summary_voice_file_ids=deserialize_voice_file_ids(
            cached.get("summary_voice_file_ids_json")
        ),
        summary_voice_voice=cached.get("summary_voice_voice"),
        summary_voice_rate=cached.get("summary_voice_rate"),
        summary_voice_provider=cached.get("summary_voice_provider"),
    )


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


async def save_catalog_document_summary_audio(
    user_id: int,
    document_id: int | None,
    voice_file_ids: list[str],
    voice: str,
    rate: str,
    provider: str,
) -> bool:
    if document_id is None:
        return False

    voice_file_ids = [
        str(file_id).strip()
        for file_id in voice_file_ids
        if str(file_id).strip()
    ]

    if not voice_file_ids:
        return False

    try:
        return await set_document_summary_audio(
            user_id=user_id,
            document_id=document_id,
            voice_file_ids_json=serialize_voice_file_ids(voice_file_ids),
            voice=voice,
            rate=rate,
            provider=provider,
        )
    except Exception:
        logger.exception(
            "DocumentCatalog: не вдалося зберегти summary audio user_id=%s document_id=%s",
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
