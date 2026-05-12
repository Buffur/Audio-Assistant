# Файл: keyboards/admin_menu.py

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

ADMIN_MENU_PREFIX = "admin_menu:"

ADMIN_MENU_MAIN_CALLBACK = f"{ADMIN_MENU_PREFIX}main"
ADMIN_MENU_STATS_CALLBACK = f"{ADMIN_MENU_PREFIX}stats"
ADMIN_MENU_USERS_CALLBACK = f"{ADMIN_MENU_PREFIX}users"
ADMIN_MENU_PREMIUM_CALLBACK = f"{ADMIN_MENU_PREFIX}premium"
ADMIN_MENU_BROADCAST_CALLBACK = f"{ADMIN_MENU_PREFIX}broadcast"
ADMIN_MENU_BANS_CALLBACK = f"{ADMIN_MENU_PREFIX}bans"
ADMIN_MENU_LIMITS_CALLBACK = f"{ADMIN_MENU_PREFIX}limits"


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
                text="💎 Premium",
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


def admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="⬅️ Назад в адмін-меню",
                callback_data=ADMIN_MENU_MAIN_CALLBACK
            )
        ]
    ])