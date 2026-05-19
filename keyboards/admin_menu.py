# Файл: keyboards/admin_menu.py

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

ADMIN_MENU_PREFIX = "admin_menu:"

ADMIN_MENU_MAIN_CALLBACK = f"{ADMIN_MENU_PREFIX}main"
ADMIN_MENU_STATS_CALLBACK = f"{ADMIN_MENU_PREFIX}stats"
ADMIN_MENU_USERS_CALLBACK = f"{ADMIN_MENU_PREFIX}users"
ADMIN_MENU_USERS_PAGE_PREFIX = f"{ADMIN_MENU_PREFIX}users_page:"
ADMIN_MENU_PREMIUM_CALLBACK = f"{ADMIN_MENU_PREFIX}premium"
ADMIN_MENU_BROADCAST_CALLBACK = f"{ADMIN_MENU_PREFIX}broadcast"
ADMIN_MENU_BANS_CALLBACK = f"{ADMIN_MENU_PREFIX}bans"
ADMIN_MENU_LIMITS_CALLBACK = f"{ADMIN_MENU_PREFIX}limits"
ADMIN_MENU_LIMIT_EDIT_PREFIX = f"{ADMIN_MENU_PREFIX}limit_edit:"
ADMIN_MENU_LIMIT_ADJUST_PREFIX = f"{ADMIN_MENU_PREFIX}limit_adjust:"
ADMIN_MENU_LIMIT_RESET_PREFIX = f"{ADMIN_MENU_PREFIX}limit_reset:"
ADMIN_MENU_USER_PREFIX = f"{ADMIN_MENU_PREFIX}user:"
ADMIN_MENU_USER_ACTION_PREFIX = f"{ADMIN_MENU_PREFIX}user_action:"
ADMIN_MENU_USER_ACTION_CONFIRM_PREFIX = (
    f"{ADMIN_MENU_PREFIX}user_action_confirm:"
)
ADMIN_MENU_USER_ACTION_CANCEL_PREFIX = f"{ADMIN_MENU_PREFIX}user_action_cancel:"
ADMIN_MENU_USER_BAN_PREFIX = f"{ADMIN_MENU_PREFIX}user_ban:"
ADMIN_MENU_USER_UNBAN_PREFIX = f"{ADMIN_MENU_PREFIX}user_unban:"
ADMIN_MENU_USER_LIMIT_PLUS_30_PREFIX = f"{ADMIN_MENU_PREFIX}user_limit_plus_30:"
ADMIN_MENU_USER_LIMIT_PLUS_FOREVER_PREFIX = (
    f"{ADMIN_MENU_PREFIX}user_limit_plus_forever:"
)
ADMIN_MENU_USER_LIMIT_PLUS_REVOKE_PREFIX = (
    f"{ADMIN_MENU_PREFIX}user_limit_plus_revoke:"
)

ADMIN_USER_ACTION_BAN = "ban"
ADMIN_USER_ACTION_UNBAN = "unban"
ADMIN_USER_ACTION_LIMIT_PLUS_30 = "limit_plus_30"
ADMIN_USER_ACTION_LIMIT_PLUS_FOREVER = "limit_plus_forever"
ADMIN_USER_ACTION_LIMIT_PLUS_REVOKE = "limit_plus_revoke"
ADMIN_USER_ACTION_RESET_LIMITS = "reset_limits"

ADMIN_USER_ACTIONS = {
    ADMIN_USER_ACTION_BAN,
    ADMIN_USER_ACTION_UNBAN,
    ADMIN_USER_ACTION_LIMIT_PLUS_30,
    ADMIN_USER_ACTION_LIMIT_PLUS_FOREVER,
    ADMIN_USER_ACTION_LIMIT_PLUS_REVOKE,
    ADMIN_USER_ACTION_RESET_LIMITS,
}


def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📊 Статистика",
                callback_data=ADMIN_MENU_STATS_CALLBACK
            ),
            InlineKeyboardButton(
                text="👥 Користувачі",
                callback_data=ADMIN_MENU_USERS_CALLBACK
            ),
        ],
        [
            InlineKeyboardButton(
                text="💎 Ліміт+",
                callback_data=ADMIN_MENU_PREMIUM_CALLBACK
            ),
            InlineKeyboardButton(
                text="📢 Розсилка",
                callback_data=ADMIN_MENU_BROADCAST_CALLBACK
            ),
        ],
        [
            InlineKeyboardButton(
                text="🚫 Бан / Розбан",
                callback_data=ADMIN_MENU_BANS_CALLBACK
            ),
            InlineKeyboardButton(
                text="⚙️ Ліміти",
                callback_data=ADMIN_MENU_LIMITS_CALLBACK
            ),
        ],
    ])


def admin_back_keyboard(
    refresh_callback: str | None = None
) -> InlineKeyboardMarkup:
    keyboard = []

    if refresh_callback:
        keyboard.append([
            InlineKeyboardButton(
                text="🔄 Оновити",
                callback_data=refresh_callback
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад в адмін-меню",
            callback_data=ADMIN_MENU_MAIN_CALLBACK
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_admin_limit_edit_callback(limit_name: str) -> str:
    return f"{ADMIN_MENU_LIMIT_EDIT_PREFIX}{limit_name}"


def build_admin_limit_adjust_callback(limit_name: str, delta: int) -> str:
    return f"{ADMIN_MENU_LIMIT_ADJUST_PREFIX}{limit_name}:{delta}"


def build_admin_limit_reset_callback(limit_name: str) -> str:
    return f"{ADMIN_MENU_LIMIT_RESET_PREFIX}{limit_name}"


def parse_admin_limit_name_callback(
    callback_data: str | None,
    prefix: str
) -> str | None:
    if not callback_data:
        return None

    if not callback_data.startswith(prefix):
        return None

    limit_name = callback_data.removeprefix(prefix).split(":", 1)[0]

    if not limit_name:
        return None

    return limit_name


def parse_admin_limit_adjust_callback(
    callback_data: str | None
) -> tuple[str, int] | None:
    if not callback_data:
        return None

    if not callback_data.startswith(ADMIN_MENU_LIMIT_ADJUST_PREFIX):
        return None

    raw_value = callback_data.removeprefix(ADMIN_MENU_LIMIT_ADJUST_PREFIX)
    parts = raw_value.rsplit(":", 1)

    if len(parts) != 2:
        return None

    limit_name, raw_delta = parts

    if not limit_name:
        return None

    try:
        delta = int(raw_delta)
    except ValueError:
        return None

    return limit_name, delta


def admin_limits_keyboard(limits: dict[str, int]) -> InlineKeyboardMarkup:
    labels = {
        "text_messages_limit": "💬 Текстові",
        "files_limit": "📄 Файли",
        "ocr_limit": "🖼 Фото",
        "links_limit": "🔗 Посилання",
        "summaries_limit": "📝 Змісти",
    }

    keyboard = []

    for limit_name, label in labels.items():
        keyboard.append([
            InlineKeyboardButton(
                text=f"{label}: {limits[limit_name]}",
                callback_data=build_admin_limit_edit_callback(limit_name)
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="🔄 Оновити",
            callback_data=ADMIN_MENU_LIMITS_CALLBACK
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад в адмін-меню",
            callback_data=ADMIN_MENU_MAIN_CALLBACK
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def admin_limit_edit_keyboard(limit_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="-10",
                callback_data=build_admin_limit_adjust_callback(limit_name, -10)
            ),
            InlineKeyboardButton(
                text="-1",
                callback_data=build_admin_limit_adjust_callback(limit_name, -1)
            ),
            InlineKeyboardButton(
                text="+1",
                callback_data=build_admin_limit_adjust_callback(limit_name, 1)
            ),
            InlineKeyboardButton(
                text="+10",
                callback_data=build_admin_limit_adjust_callback(limit_name, 10)
            ),
        ],
        [
            InlineKeyboardButton(
                text="↩️ За замовчуванням",
                callback_data=build_admin_limit_reset_callback(limit_name)
            )
        ],
        [
            InlineKeyboardButton(
                text="⚙️ До лімітів",
                callback_data=ADMIN_MENU_LIMITS_CALLBACK
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад в адмін-меню",
                callback_data=ADMIN_MENU_MAIN_CALLBACK
            )
        ],
    ])


def build_admin_users_page_callback(page: int) -> str:
    return f"{ADMIN_MENU_USERS_PAGE_PREFIX}{max(page, 0)}"


def build_admin_user_action_callback(
    prefix: str,
    action: str,
    user_id: int,
) -> str:
    return f"{prefix}{action}:{user_id}"


def parse_admin_user_action_callback(
    callback_data: str | None,
    prefix: str,
) -> tuple[str, int] | None:
    if not callback_data:
        return None

    if not callback_data.startswith(prefix):
        return None

    raw_value = callback_data.removeprefix(prefix)
    parts = raw_value.rsplit(":", 1)

    if len(parts) != 2:
        return None

    action, raw_user_id = parts

    if action not in ADMIN_USER_ACTIONS:
        return None

    if not raw_user_id.isdigit():
        return None

    return action, int(raw_user_id)


def parse_admin_users_page_callback(callback_data: str | None) -> int | None:
    if not callback_data:
        return None

    if not callback_data.startswith(ADMIN_MENU_USERS_PAGE_PREFIX):
        return None

    raw_page = callback_data.removeprefix(ADMIN_MENU_USERS_PAGE_PREFIX)

    if not raw_page.isdigit():
        return None

    return int(raw_page)


def admin_users_keyboard(
    users: list[dict],
    page: int,
    total_pages: int,
    page_size: int = 10
) -> InlineKeyboardMarkup:
    keyboard = []
    page = max(page, 0)
    total_pages = max(total_pages, 1)
    start_index = page * page_size
    page_users = users[start_index:start_index + page_size]

    for user in page_users:
        user_id = user["user_id"]
        status_icon = "🚫" if user.get("is_banned") else "✅"
        plan_icon = "💎" if user.get("plan") == "premium" else "🎯"
        username = str(user.get("username") or "").strip()
        full_name = str(user.get("full_name") or "").strip()
        display_name = username or full_name or str(user_id)

        if len(display_name) > 18:
            display_name = display_name[:17] + "..."

        keyboard.append([
            InlineKeyboardButton(
                text=f"{status_icon} {plan_icon} {display_name} · {user_id}",
                callback_data=f"{ADMIN_MENU_USER_PREFIX}{user_id}"
            )
        ])

    navigation_row = []

    if page > 0:
        navigation_row.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=build_admin_users_page_callback(page - 1)
            )
        )

    navigation_row.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data=build_admin_users_page_callback(page)
        )
    )

    if page + 1 < total_pages:
        navigation_row.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=build_admin_users_page_callback(page + 1)
            )
        )

    keyboard.append(navigation_row)
    keyboard.append([
        InlineKeyboardButton(
            text="🔄 Оновити",
            callback_data=build_admin_users_page_callback(page)
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад в адмін-меню",
            callback_data=ADMIN_MENU_MAIN_CALLBACK
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def admin_user_actions_keyboard(
    user_id: int,
    is_banned: bool,
    is_limit_plus: bool,
    can_ban: bool = True
) -> InlineKeyboardMarkup:
    keyboard = []

    if can_ban:
        if is_banned:
            keyboard.append([
                InlineKeyboardButton(
                    text="✅ Розблокувати",
                    callback_data=build_admin_user_action_callback(
                        ADMIN_MENU_USER_ACTION_PREFIX,
                        ADMIN_USER_ACTION_UNBAN,
                        user_id,
                    )
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    text="🚫 Заблокувати",
                    callback_data=build_admin_user_action_callback(
                        ADMIN_MENU_USER_ACTION_PREFIX,
                        ADMIN_USER_ACTION_BAN,
                        user_id,
                    )
                )
            ])

    keyboard.append([
        InlineKeyboardButton(
            text="💎 Ліміт+ 30 днів",
            callback_data=build_admin_user_action_callback(
                ADMIN_MENU_USER_ACTION_PREFIX,
                ADMIN_USER_ACTION_LIMIT_PLUS_30,
                user_id,
            )
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            text="♾️ Ліміт+ безстроково",
            callback_data=build_admin_user_action_callback(
                ADMIN_MENU_USER_ACTION_PREFIX,
                ADMIN_USER_ACTION_LIMIT_PLUS_FOREVER,
                user_id,
            )
        )
    ])

    if is_limit_plus:
        keyboard.append([
            InlineKeyboardButton(
                text="➖ Зняти Ліміт+",
                callback_data=build_admin_user_action_callback(
                    ADMIN_MENU_USER_ACTION_PREFIX,
                    ADMIN_USER_ACTION_LIMIT_PLUS_REVOKE,
                    user_id,
                )
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="🔄 Обнулити ліміти за сьогодні",
            callback_data=build_admin_user_action_callback(
                ADMIN_MENU_USER_ACTION_PREFIX,
                ADMIN_USER_ACTION_RESET_LIMITS,
                user_id,
            )
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            text="👥 До користувачів",
            callback_data=ADMIN_MENU_USERS_CALLBACK
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад в адмін-меню",
            callback_data=ADMIN_MENU_MAIN_CALLBACK
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def admin_user_action_confirmation_keyboard(
    action: str,
    user_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Підтвердити",
                callback_data=build_admin_user_action_callback(
                    ADMIN_MENU_USER_ACTION_CONFIRM_PREFIX,
                    action,
                    user_id,
                ),
            )
        ],
        [
            InlineKeyboardButton(
                text="↩️ Скасувати",
                callback_data=build_admin_user_action_callback(
                    ADMIN_MENU_USER_ACTION_CANCEL_PREFIX,
                    action,
                    user_id,
                ),
            )
        ],
    ])
