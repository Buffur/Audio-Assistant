# Файл: handlers/catalog.py

import logging
import uuid

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import Message

from keyboards.catalog import (
    CATALOG_DELETE_PREFIX,
    CATALOG_OPEN_PREFIX,
    CATALOG_UNAVAILABLE_PREFIX,
    catalog_keyboard,
    parse_catalog_document_id,
)
from services.document_history_service import (
    clear_document_history,
    delete_catalog_document,
    get_catalog_document_chunks,
    get_recent_document_history,
)
from services.reading_service import (
    cleanup_session,
    safe_delete_message,
    send_audio_chunk,
)
from services.reading_session_store import (
    has_reading_session,
    set_reading_session,
    set_reading_session_generating,
)
from texts.catalog import (
    CATALOG_CLEARED_TEXT,
    CATALOG_DOCUMENT_DELETED_TEXT,
    CATALOG_DOCUMENT_NOT_FOUND_TEXT,
    CATALOG_DOCUMENT_WITHOUT_CHUNKS_TEXT,
    CATALOG_HELP_TEXT,
    CATALOG_OPENING_TEXT,
    build_catalog_document_opened_text,
    build_catalog_text,
)

router = Router()
logger = logging.getLogger(__name__)


def _generate_session_id() -> str:
    return uuid.uuid4().hex[:12]


async def _send_catalog(message: Message, user_id: int) -> None:
    """
    Надсилає каталог користувачу.
    """
    items = await get_recent_document_history(user_id=user_id)
    text = build_catalog_text(items)
    keyboard = catalog_keyboard(items)

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def _refresh_catalog_message(message: Message, user_id: int) -> None:
    """
    Оновлює вже існуюче повідомлення каталогу після видалення документа.

    Якщо редагування не вдалося — надсилає каталог новим повідомленням.
    """
    items = await get_recent_document_history(user_id=user_id)
    text = build_catalog_text(items)
    keyboard = catalog_keyboard(items)

    try:
        await message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception:
        logger.exception("Catalog: не вдалося оновити повідомлення каталогу")
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )


@router.message(Command("catalog"))
@router.message(Command("history"))
async def catalog_handler(message: Message) -> None:
    """
    Показує каталог останніх матеріалів користувача.
    """
    user_id = message.from_user.id
    await _send_catalog(message, user_id)


@router.message(Command("catalog_clear"))
@router.message(Command("history_clear"))
async def catalog_clear_handler(message: Message) -> None:
    """
    Очищає каталог матеріалів користувача.
    """
    user_id = message.from_user.id

    await clear_document_history(user_id=user_id)
    await message.answer(CATALOG_CLEARED_TEXT)


@router.message(Command("catalog_help"))
@router.message(Command("history_help"))
async def catalog_help_handler(message: Message) -> None:
    """
    Показує довідку по каталогу.
    """
    await message.answer(CATALOG_HELP_TEXT)


@router.callback_query(F.data.startswith(CATALOG_UNAVAILABLE_PREFIX))
async def unavailable_catalog_document(callback: types.CallbackQuery) -> None:
    """
    Пояснює, чому старий запис не можна відкрити повторно.
    """
    await callback.answer(
        CATALOG_DOCUMENT_WITHOUT_CHUNKS_TEXT,
        show_alert=True
    )


@router.callback_query(F.data.startswith(CATALOG_OPEN_PREFIX))
async def open_catalog_document(callback: types.CallbackQuery) -> None:
    """
    Відкриває документ із каталогу і створює нову reading session.
    """
    user_id = callback.from_user.id

    document_id = parse_catalog_document_id(
        callback_data=callback.data,
        prefix=CATALOG_OPEN_PREFIX
    )

    if document_id is None:
        await callback.answer(CATALOG_DOCUMENT_NOT_FOUND_TEXT, show_alert=True)
        return

    document, chunks = await get_catalog_document_chunks(
        user_id=user_id,
        document_id=document_id
    )

    if not document:
        await callback.answer(CATALOG_DOCUMENT_NOT_FOUND_TEXT, show_alert=True)
        return

    if not chunks:
        await callback.answer(
            CATALOG_DOCUMENT_WITHOUT_CHUNKS_TEXT,
            show_alert=True
        )
        return

    await callback.answer("Відкриваю документ...")

    status_msg = await callback.message.answer(CATALOG_OPENING_TEXT)

    await cleanup_session(user_id)

    await set_reading_session(
        user_id=user_id,
        session={
            "session_id": _generate_session_id(),
            "chunks": chunks,
            "index": 0,
            "is_generating": True,
            "prefetch_task": None,
        }
    )

    await callback.message.answer(
        build_catalog_document_opened_text(
            source_name=document.get("source_name") or "Документ",
            chunks_count=len(chunks)
        ),
        parse_mode="HTML"
    )

    await safe_delete_message(status_msg)

    try:
        await send_audio_chunk(callback.message, user_id)

    finally:
        if await has_reading_session(user_id):
            await set_reading_session_generating(user_id, False)


@router.callback_query(F.data.startswith(CATALOG_DELETE_PREFIX))
async def delete_catalog_document_handler(callback: types.CallbackQuery) -> None:
    """
    Видаляє конкретний документ із каталогу і оновлює список.
    """
    user_id = callback.from_user.id

    document_id = parse_catalog_document_id(
        callback_data=callback.data,
        prefix=CATALOG_DELETE_PREFIX
    )

    if document_id is None:
        await callback.answer(CATALOG_DOCUMENT_NOT_FOUND_TEXT, show_alert=True)
        return

    await delete_catalog_document(
        user_id=user_id,
        document_id=document_id
    )

    await callback.answer(CATALOG_DOCUMENT_DELETED_TEXT)

    await _refresh_catalog_message(
        message=callback.message,
        user_id=user_id
    )