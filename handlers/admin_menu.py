# Файл: handlers/admin_menu.py

import logging
from datetime import datetime

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import Message

from config import ADMIN_IDS
from database.db import get_all_users_detailed, get_daily_usage
from keyboards.admin_menu import (
    ADMIN_MENU_BANS_CALLBACK,
    ADMIN_MENU_BROADCAST_CALLBACK,
    ADMIN_MENU_LIMITS_CALLBACK,
    ADMIN_MENU_MAIN_CALLBACK,
    ADMIN_MENU_PREMIUM_CALLBACK,
    ADMIN_MENU_STATS_CALLBACK,
    ADMIN_MENU_USERS_CALLBACK,
    admin_back_keyboard,
    admin_main_keyboard,
)
from texts.admin_menu import (
    ADMIN_ACCESS_DENIED_TEXT,
    ADMIN_BANS_TEXT,
    ADMIN_BROADCAST_TEXT,
    ADMIN_MENU_TEXT,
    ADMIN_PREMIUM_TEXT,
    build_admin_limits_text,
    build_admin_stats_text,
    build_admin_users_text,
)

router = Router()
logger = logging.getLogger(__name__)


def _is_admin_user(user_id: int | None) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


async def _safe_edit_admin_message(
    callback: types.CallbackQuery,
    text: str,
    reply_markup
) -> None:
    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    except Exception:
        logger.exception("AdminMenu: не вдалося оновити повідомлення меню")
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )


async def _build_stats_text() -> str:
    users = await get_all_users_detailed()

    total_users = len(users)
    banned_users = sum(1 for user in users if user.get("is_banned"))
    active_users = total_users - banned_users

    premium_users = sum(
        1 for user in users
        if (user.get("plan") or "free") == "premium"
    )
    free_users = total_users - premium_users

    today = datetime.now().date().isoformat()

    usage_totals = {
        "text_messages_processed": 0,
        "files_processed": 0,
        "ocr_processed": 0,
        "links_processed": 0,
        "summaries_generated": 0,
    }

    for user in users:
        usage = await get_daily_usage(
            user_id=user["user_id"],
            usage_date=today
        )

        for key in usage_totals:
            usage_totals[key] += usage.get(key, 0)

    return build_admin_stats_text(
        total_users=total_users,
        active_users=active_users,
        banned_users=banned_users,
        free_users=free_users,
        premium_users=premium_users,
        usage_totals=usage_totals
    )


@router.message(Command("admin"))
async def admin_menu_handler(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None

    if not _is_admin_user(user_id):
        await message.answer(ADMIN_ACCESS_DENIED_TEXT)
        return

    await message.answer(
        ADMIN_MENU_TEXT,
        parse_mode="HTML",
        reply_markup=admin_main_keyboard()
    )


@router.callback_query(F.data == ADMIN_MENU_MAIN_CALLBACK)
async def admin_menu_main_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    await _safe_edit_admin_message(
        callback=callback,
        text=ADMIN_MENU_TEXT,
        reply_markup=admin_main_keyboard()
    )

    await callback.answer()


@router.callback_query(F.data == ADMIN_MENU_STATS_CALLBACK)
async def admin_stats_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    text = await _build_stats_text()

    await _safe_edit_admin_message(
        callback=callback,
        text=text,
        reply_markup=admin_back_keyboard()
    )

    await callback.answer()


@router.callback_query(F.data == ADMIN_MENU_USERS_CALLBACK)
async def admin_users_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    users = await get_all_users_detailed()
    text = build_admin_users_text(users)

    await _safe_edit_admin_message(
        callback=callback,
        text=text,
        reply_markup=admin_back_keyboard()
    )

    await callback.answer()


@router.callback_query(F.data == ADMIN_MENU_PREMIUM_CALLBACK)
async def admin_premium_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    await _safe_edit_admin_message(
        callback=callback,
        text=ADMIN_PREMIUM_TEXT,
        reply_markup=admin_back_keyboard()
    )

    await callback.answer()


@router.callback_query(F.data == ADMIN_MENU_BROADCAST_CALLBACK)
async def admin_broadcast_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    await _safe_edit_admin_message(
        callback=callback,
        text=ADMIN_BROADCAST_TEXT,
        reply_markup=admin_back_keyboard()
    )

    await callback.answer()


@router.callback_query(F.data == ADMIN_MENU_BANS_CALLBACK)
async def admin_bans_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    await _safe_edit_admin_message(
        callback=callback,
        text=ADMIN_BANS_TEXT,
        reply_markup=admin_back_keyboard()
    )

    await callback.answer()


@router.callback_query(F.data == ADMIN_MENU_LIMITS_CALLBACK)
async def admin_limits_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    await _safe_edit_admin_message(
        callback=callback,
        text=build_admin_limits_text(),
        reply_markup=admin_back_keyboard()
    )

    await callback.answer()