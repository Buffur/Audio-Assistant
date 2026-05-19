# Файл: handlers/catalog.py

import logging
import uuid

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import Message

from keyboards.catalog import (
    CATALOG_CLEAR_CANCEL_CALLBACK,
    CATALOG_CLEAR_CONFIRM_CALLBACK,
    CATALOG_DELETE_CANCEL_PREFIX,
    CATALOG_DELETE_CONFIRM_PREFIX,
    CATALOG_DELETE_PREFIX,
    CATALOG_OPEN_PREFIX,
    CATALOG_PAGE_PREFIX,
    CATALOG_UNAVAILABLE_PREFIX,
    catalog_clear_confirmation_keyboard,
    catalog_keyboard,
    catalog_delete_confirmation_keyboard,
    parse_catalog_page,
    parse_catalog_document_id,
)
from services.document_history_service import (
    clear_document_history,
    count_recent_document_history,
    delete_catalog_document,
    deserialize_voice_file_ids,
    get_catalog_document_chunks,
    DEFAULT_HISTORY_LIMIT,
    get_recent_document_history,
)
from services.reading_service import (
    cleanup_session,
    safe_delete_message,
    send_audio_chunk,
)
from services.reading_session_store import (
    set_reading_session,
)
from texts.catalog import (
    CATALOG_CLEARED_TEXT,
    CATALOG_CLEAR_CANCELLED_TEXT,
    CATALOG_CLEAR_CONFIRM_TEXT,
    CATALOG_DELETE_CONFIRM_TEXT,
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

CATALOG_PAGE_SIZE = DEFAULT_HISTORY_LIMIT


def _generate_session_id() -> str:
    return uuid.uuid4().hex[:12]


def _build_catalog_reading_session(document: dict, chunks: list[str]) -> dict:
    session = {
        "session_id": _generate_session_id(),
        "chunks": chunks,
        "index": 0,
        "is_generating": True,
        "prefetch_task": None,
        "catalog_document_id": document.get("id"),
    }

    summary_text = str(document.get("summary_text") or "").strip()

    if summary_text:
        session["summary_text"] = summary_text
        session["summary_delivered"] = False

        summary_voice_file_ids = deserialize_voice_file_ids(
            document.get("summary_voice_file_ids_json")
        )

        if summary_voice_file_ids:
            session["summary_voice_file_ids"] = summary_voice_file_ids
            session["summary_voice_voice"] = document.get("summary_voice_voice")
            session["summary_voice_rate"] = document.get("summary_voice_rate")
            session["summary_voice_provider"] = document.get(
                "summary_voice_provider"
            )

    return session


def _clamp_page(page: int, total_items: int, page_size: int) -> tuple[int, int]:
    total_pages = max((total_items + page_size - 1) // page_size, 1)
    page = min(max(page, 0), total_pages - 1)

    return page, total_pages


async def _get_catalog_page(
    user_id: int,
    page: int
) -> tuple[list[dict], int, int, int]:
    total_items = await count_recent_document_history(user_id=user_id)
    page, total_pages = _clamp_page(
        page=page,
        total_items=total_items,
        page_size=CATALOG_PAGE_SIZE,
    )
    items = await get_recent_document_history(
        user_id=user_id,
        limit=CATALOG_PAGE_SIZE,
        offset=page * CATALOG_PAGE_SIZE,
    )

    return items, page, total_pages, total_items


async def _send_catalog(message: Message, user_id: int, page: int = 0) -> None:
    """
    Надсилає каталог користувачу.
    """
    items, page, total_pages, total_items = await _get_catalog_page(
        user_id=user_id,
        page=page,
    )
    text = build_catalog_text(
        items,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        page_size=CATALOG_PAGE_SIZE,
    )
    keyboard = catalog_keyboard(
        items,
        page=page,
        total_pages=total_pages,
        page_size=CATALOG_PAGE_SIZE,
    )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def _refresh_catalog_message(
    message: Message,
    user_id: int,
    page: int = 0
) -> None:
    """
    Оновлює вже існуюче повідомлення каталогу після видалення документа.

    Якщо редагування не вдалося — надсилає каталог новим повідомленням.
    """
    items, page, total_pages, total_items = await _get_catalog_page(
        user_id=user_id,
        page=page,
    )
    text = build_catalog_text(
        items,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        page_size=CATALOG_PAGE_SIZE,
    )
    keyboard = catalog_keyboard(
        items,
        page=page,
        total_pages=total_pages,
        page_size=CATALOG_PAGE_SIZE,
    )

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


@router.callback_query(F.data.startswith(CATALOG_PAGE_PREFIX))
async def catalog_page_callback(callback: types.CallbackQuery) -> None:
    """
    Перемикає сторінки каталогу в тому самому повідомленні.
    """
    user_id = callback.from_user.id
    page = parse_catalog_page(callback.data, CATALOG_PAGE_PREFIX)

    if page is None:
        await callback.answer(CATALOG_DOCUMENT_NOT_FOUND_TEXT, show_alert=True)
        return

    await _refresh_catalog_message(
        message=callback.message,
        user_id=user_id,
        page=page,
    )
    await callback.answer()


@router.message(Command("catalog_clear"))
@router.message(Command("history_clear"))
async def catalog_clear_handler(message: Message) -> None:
    """
    Просить підтвердження перед очищенням каталогу матеріалів користувача.
    """
    await message.answer(
        CATALOG_CLEAR_CONFIRM_TEXT,
        reply_markup=catalog_clear_confirmation_keyboard(),
    )


@router.callback_query(F.data == CATALOG_CLEAR_CONFIRM_CALLBACK)
async def catalog_clear_confirm_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id

    await clear_document_history(user_id=user_id)

    if callback.message:
        await callback.message.edit_text(CATALOG_CLEARED_TEXT)

    await callback.answer(CATALOG_CLEARED_TEXT)


@router.callback_query(F.data == CATALOG_CLEAR_CANCEL_CALLBACK)
async def catalog_clear_cancel_callback(callback: types.CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_text(CATALOG_CLEAR_CANCELLED_TEXT)

    await callback.answer(CATALOG_CLEAR_CANCELLED_TEXT)


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
        session=_build_catalog_reading_session(document, chunks),
    )

    await callback.message.answer(
        build_catalog_document_opened_text(
            source_name=document.get("source_name") or "Документ",
            chunks_count=len(chunks)
        ),
        parse_mode="HTML"
    )

    await safe_delete_message(status_msg)

    await send_audio_chunk(callback.message, user_id)


@router.callback_query(F.data.startswith(CATALOG_DELETE_CONFIRM_PREFIX))
async def confirm_catalog_document_delete(callback: types.CallbackQuery) -> None:
    """
    Показує підтвердження перед видаленням документа.
    """
    document_id = parse_catalog_document_id(
        callback_data=callback.data,
        prefix=CATALOG_DELETE_CONFIRM_PREFIX,
    )

    if document_id is None:
        await callback.answer(CATALOG_DOCUMENT_NOT_FOUND_TEXT, show_alert=True)
        return

    page = parse_catalog_page(callback.data, CATALOG_DELETE_CONFIRM_PREFIX) or 0

    await callback.message.edit_text(
        CATALOG_DELETE_CONFIRM_TEXT,
        reply_markup=catalog_delete_confirmation_keyboard(
            document_id=document_id,
            page=page,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(CATALOG_DELETE_CANCEL_PREFIX))
async def cancel_catalog_document_delete(callback: types.CallbackQuery) -> None:
    """
    Повертає каталог після скасування видалення.
    """
    user_id = callback.from_user.id
    page = parse_catalog_page(callback.data, CATALOG_DELETE_CANCEL_PREFIX) or 0

    await _refresh_catalog_message(
        message=callback.message,
        user_id=user_id,
        page=page,
    )
    await callback.answer("Видалення скасовано.")


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

    page = parse_catalog_page(callback.data, CATALOG_DELETE_PREFIX) or 0

    await _refresh_catalog_message(
        message=callback.message,
        user_id=user_id,
        page=page,
    )
