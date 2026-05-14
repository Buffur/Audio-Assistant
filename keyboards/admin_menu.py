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
ADMIN_MENU_USER_BAN_PREFIX = f"{ADMIN_MENU_PREFIX}user_ban:"
ADMIN_MENU_USER_UNBAN_PREFIX = f"{ADMIN_MENU_PREFIX}user_unban:"
ADMIN_MENU_USER_LIMIT_PLUS_30_PREFIX = f"{ADMIN_MENU_PREFIX}user_limit_plus_30:"
ADMIN_MENU_USER_LIMIT_PLUS_FOREVER_PREFIX = (
    f"{ADMIN_MENU_PREFIX}user_limit_plus_forever:"
)
ADMIN_MENU_USER_LIMIT_PLUS_REVOKE_PREFIX = (
    f"{ADMIN_MENU_PREFIX}user_limit_plus_revoke:"
)


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
                text="↩️ Скинути до .env",
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

        keyboard.append([
            InlineKeyboardButton(
                text=f"{status_icon} {plan_icon} {user_id}",
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
                    callback_data=f"{ADMIN_MENU_USER_UNBAN_PREFIX}{user_id}"
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    text="🚫 Заблокувати",
                    callback_data=f"{ADMIN_MENU_USER_BAN_PREFIX}{user_id}"
                )
            ])

    keyboard.append([
        InlineKeyboardButton(
            text="💎 Ліміт+ 30 днів",
            callback_data=f"{ADMIN_MENU_USER_LIMIT_PLUS_30_PREFIX}{user_id}"
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            text="♾️ Ліміт+ безстроково",
            callback_data=f"{ADMIN_MENU_USER_LIMIT_PLUS_FOREVER_PREFIX}{user_id}"
        )
    ])

    if is_limit_plus:
        keyboard.append([
            InlineKeyboardButton(
                text="➖ Зняти Ліміт+",
                callback_data=f"{ADMIN_MENU_USER_LIMIT_PLUS_REVOKE_PREFIX}{user_id}"
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
