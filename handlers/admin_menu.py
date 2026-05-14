# Файл: handlers/admin_menu.py

import logging
from datetime import datetime

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import Message

from config import ADMIN_IDS
from database.db import ban_user, get_all_users_detailed, get_daily_usage, unban_user
from keyboards.admin_menu import (
    ADMIN_MENU_BANS_CALLBACK,
    ADMIN_MENU_BROADCAST_CALLBACK,
    ADMIN_MENU_LIMIT_ADJUST_PREFIX,
    ADMIN_MENU_LIMIT_EDIT_PREFIX,
    ADMIN_MENU_LIMIT_RESET_PREFIX,
    ADMIN_MENU_LIMITS_CALLBACK,
    ADMIN_MENU_MAIN_CALLBACK,
    ADMIN_MENU_PREMIUM_CALLBACK,
    ADMIN_MENU_STATS_CALLBACK,
    ADMIN_MENU_USERS_CALLBACK,
    ADMIN_MENU_USERS_PAGE_PREFIX,
    ADMIN_MENU_USER_BAN_PREFIX,
    ADMIN_MENU_USER_LIMIT_PLUS_30_PREFIX,
    ADMIN_MENU_USER_LIMIT_PLUS_FOREVER_PREFIX,
    ADMIN_MENU_USER_LIMIT_PLUS_REVOKE_PREFIX,
    ADMIN_MENU_USER_PREFIX,
    ADMIN_MENU_USER_UNBAN_PREFIX,
    admin_limit_edit_keyboard,
    admin_limits_keyboard,
    admin_user_actions_keyboard,
    admin_users_keyboard,
    admin_back_keyboard,
    admin_main_keyboard,
    parse_admin_limit_adjust_callback,
    parse_admin_limit_name_callback,
    parse_admin_users_page_callback,
)
from services.usage_limits_service import (
    DEFAULT_LIMITS,
    adjust_editable_limit,
    get_effective_plan_info,
    get_editable_limits,
    grant_premium,
    revoke_premium,
    reset_editable_limit,
)
from texts.admin_menu import (
    ADMIN_ACCESS_DENIED_TEXT,
    ADMIN_BANS_TEXT,
    ADMIN_BROADCAST_TEXT,
    ADMIN_MENU_TEXT,
    ADMIN_PREMIUM_TEXT,
    build_admin_limit_edit_text,
    build_admin_limits_text,
    build_admin_stats_text,
    build_admin_user_detail_text,
    build_admin_users_text,
)

router = Router()
logger = logging.getLogger(__name__)

ADMIN_USERS_PAGE_SIZE = 10


def _is_admin_user(user_id: int | None) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


def _is_message_not_modified_error(error: Exception) -> bool:
    return "message is not modified" in str(error).lower()


def _parse_user_id_from_callback(
    callback_data: str | None,
    prefix: str
) -> int | None:
    if not callback_data:
        return None

    if not callback_data.startswith(prefix):
        return None

    raw_user_id = callback_data.removeprefix(prefix)

    if not raw_user_id.isdigit():
        return None

    return int(raw_user_id)


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
    except Exception as error:
        if _is_message_not_modified_error(error):
            return

        logger.exception("AdminMenu: не вдалося оновити повідомлення меню")
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )


async def _get_admin_user(target_user_id: int) -> dict | None:
    users = await get_all_users_detailed()

    for user in users:
        if user["user_id"] == target_user_id:
            return user

    return None


def _clamp_page(page: int, total_items: int, page_size: int) -> tuple[int, int]:
    total_pages = max((total_items + page_size - 1) // page_size, 1)
    page = min(max(page, 0), total_pages - 1)

    return page, total_pages


async def _show_admin_users_page(
    callback: types.CallbackQuery,
    page: int = 0
) -> None:
    users = await get_all_users_detailed()
    page, total_pages = _clamp_page(
        page=page,
        total_items=len(users),
        page_size=ADMIN_USERS_PAGE_SIZE,
    )
    text = build_admin_users_text(
        users,
        page=page,
        page_size=ADMIN_USERS_PAGE_SIZE,
    )

    await _safe_edit_admin_message(
        callback=callback,
        text=text,
        reply_markup=admin_users_keyboard(
            users,
            page=page,
            total_pages=total_pages,
            page_size=ADMIN_USERS_PAGE_SIZE,
        )
    )


async def _show_admin_user_detail(
    callback: types.CallbackQuery,
    target_user_id: int
) -> bool:
    user = await _get_admin_user(target_user_id)

    if user is None:
        await callback.answer("Користувача не знайдено.", show_alert=True)
        return False

    plan_info = await get_effective_plan_info(target_user_id)
    user = {
        **user,
        "plan": plan_info["plan"],
        "premium_until": plan_info["premium_until"],
    }

    await _safe_edit_admin_message(
        callback=callback,
        text=build_admin_user_detail_text(user),
        reply_markup=admin_user_actions_keyboard(
            user_id=target_user_id,
            is_banned=user["is_banned"],
            is_limit_plus=plan_info["is_premium"],
            can_ban=target_user_id not in ADMIN_IDS,
        )
    )
    return True


async def _show_admin_limits(callback: types.CallbackQuery) -> None:
    limits = await get_editable_limits()

    await _safe_edit_admin_message(
        callback=callback,
        text=build_admin_limits_text(limits),
        reply_markup=admin_limits_keyboard(limits)
    )


async def _show_admin_limit_edit(
    callback: types.CallbackQuery,
    limit_name: str
) -> bool:
    limits = await get_editable_limits()

    if limit_name not in limits:
        await callback.answer("Некоректний ліміт.", show_alert=True)
        return False

    await _safe_edit_admin_message(
        callback=callback,
        text=build_admin_limit_edit_text(
            limit_name=limit_name,
            current_value=limits[limit_name],
            default_value=DEFAULT_LIMITS[limit_name],
        ),
        reply_markup=admin_limit_edit_keyboard(limit_name)
    )
    return True


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
        reply_markup=admin_back_keyboard(
            refresh_callback=ADMIN_MENU_STATS_CALLBACK
        )
    )

    await callback.answer()


@router.callback_query(F.data == ADMIN_MENU_USERS_CALLBACK)
async def admin_users_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    await _show_admin_users_page(callback, page=0)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MENU_USERS_PAGE_PREFIX))
async def admin_users_page_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    page = parse_admin_users_page_callback(callback.data)

    if page is None:
        await callback.answer("Некоректна сторінка.", show_alert=True)
        return

    await _show_admin_users_page(callback, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MENU_USER_PREFIX))
async def admin_user_detail_callback(callback: types.CallbackQuery) -> None:
    admin_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(admin_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    target_user_id = _parse_user_id_from_callback(
        callback.data,
        ADMIN_MENU_USER_PREFIX
    )

    if target_user_id is None:
        await callback.answer("Некоректний ID користувача.", show_alert=True)
        return

    if await _show_admin_user_detail(callback, target_user_id):
        await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MENU_USER_BAN_PREFIX))
async def admin_user_ban_callback(callback: types.CallbackQuery) -> None:
    admin_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(admin_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    target_user_id = _parse_user_id_from_callback(
        callback.data,
        ADMIN_MENU_USER_BAN_PREFIX
    )

    if target_user_id is None:
        await callback.answer("Некоректний ID користувача.", show_alert=True)
        return

    if target_user_id in ADMIN_IDS:
        await callback.answer("Адміністратора не можна заблокувати.", show_alert=True)
        return

    await ban_user(target_user_id)
    if await _show_admin_user_detail(callback, target_user_id):
        await callback.answer("Користувача заблоковано.")


@router.callback_query(F.data.startswith(ADMIN_MENU_USER_UNBAN_PREFIX))
async def admin_user_unban_callback(callback: types.CallbackQuery) -> None:
    admin_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(admin_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    target_user_id = _parse_user_id_from_callback(
        callback.data,
        ADMIN_MENU_USER_UNBAN_PREFIX
    )

    if target_user_id is None:
        await callback.answer("Некоректний ID користувача.", show_alert=True)
        return

    await unban_user(target_user_id)
    if await _show_admin_user_detail(callback, target_user_id):
        await callback.answer("Користувача розблоковано.")


@router.callback_query(F.data.startswith(ADMIN_MENU_USER_LIMIT_PLUS_30_PREFIX))
async def admin_user_limit_plus_30_callback(callback: types.CallbackQuery) -> None:
    admin_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(admin_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    target_user_id = _parse_user_id_from_callback(
        callback.data,
        ADMIN_MENU_USER_LIMIT_PLUS_30_PREFIX
    )

    if target_user_id is None:
        await callback.answer("Некоректний ID користувача.", show_alert=True)
        return

    await grant_premium(user_id=target_user_id, days=30)
    if await _show_admin_user_detail(callback, target_user_id):
        await callback.answer("Ліміт+ видано на 30 днів.")


@router.callback_query(F.data.startswith(ADMIN_MENU_USER_LIMIT_PLUS_FOREVER_PREFIX))
async def admin_user_limit_plus_forever_callback(
    callback: types.CallbackQuery
) -> None:
    admin_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(admin_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    target_user_id = _parse_user_id_from_callback(
        callback.data,
        ADMIN_MENU_USER_LIMIT_PLUS_FOREVER_PREFIX
    )

    if target_user_id is None:
        await callback.answer("Некоректний ID користувача.", show_alert=True)
        return

    await grant_premium(user_id=target_user_id, days=None)
    if await _show_admin_user_detail(callback, target_user_id):
        await callback.answer("Ліміт+ видано безстроково.")


@router.callback_query(F.data.startswith(ADMIN_MENU_USER_LIMIT_PLUS_REVOKE_PREFIX))
async def admin_user_limit_plus_revoke_callback(
    callback: types.CallbackQuery
) -> None:
    admin_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(admin_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    target_user_id = _parse_user_id_from_callback(
        callback.data,
        ADMIN_MENU_USER_LIMIT_PLUS_REVOKE_PREFIX
    )

    if target_user_id is None:
        await callback.answer("Некоректний ID користувача.", show_alert=True)
        return

    await revoke_premium(user_id=target_user_id)
    if await _show_admin_user_detail(callback, target_user_id):
        await callback.answer("Ліміт+ знято.")


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

    await _show_admin_limits(callback)

    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MENU_LIMIT_EDIT_PREFIX))
async def admin_limit_edit_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    limit_name = parse_admin_limit_name_callback(
        callback.data,
        ADMIN_MENU_LIMIT_EDIT_PREFIX
    )

    if limit_name is None:
        await callback.answer("Некоректний ліміт.", show_alert=True)
        return

    if await _show_admin_limit_edit(callback, limit_name):
        await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_MENU_LIMIT_ADJUST_PREFIX))
async def admin_limit_adjust_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    parsed_value = parse_admin_limit_adjust_callback(callback.data)

    if parsed_value is None:
        await callback.answer("Некоректна зміна ліміту.", show_alert=True)
        return

    limit_name, delta = parsed_value

    try:
        await adjust_editable_limit(limit_name=limit_name, delta=delta)
    except ValueError:
        await callback.answer("Некоректний ліміт.", show_alert=True)
        return

    if await _show_admin_limit_edit(callback, limit_name):
        await callback.answer("Ліміт оновлено.")


@router.callback_query(F.data.startswith(ADMIN_MENU_LIMIT_RESET_PREFIX))
async def admin_limit_reset_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user(user_id):
        await callback.answer(ADMIN_ACCESS_DENIED_TEXT, show_alert=True)
        return

    limit_name = parse_admin_limit_name_callback(
        callback.data,
        ADMIN_MENU_LIMIT_RESET_PREFIX
    )

    if limit_name is None:
        await callback.answer("Некоректний ліміт.", show_alert=True)
        return

    try:
        await reset_editable_limit(limit_name)
    except ValueError:
        await callback.answer("Некоректний ліміт.", show_alert=True)
        return

    if await _show_admin_limit_edit(callback, limit_name):
        await callback.answer("Ліміт скинуто.")
