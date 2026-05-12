# Файл: texts/admin_menu.py

from config import (
    FREE_DAILY_FILE_LIMIT,
    FREE_DAILY_LINK_LIMIT,
    FREE_DAILY_OCR_LIMIT,
    FREE_DAILY_SUMMARY_LIMIT,
    FREE_DAILY_TEXT_MESSAGE_LIMIT,
)

ADMIN_ACCESS_DENIED_TEXT = "🚫 У вас немає доступу до адмін-меню."

ADMIN_MENU_TEXT = (
    "🛠 <b>Адмін-меню</b>\n\n"
    "Оберіть потрібний розділ:"
)

ADMIN_BROADCAST_TEXT = (
    "📢 <b>Розсилка</b>\n\n"
    "Щоб зробити голосову розсилку всім активним користувачам, використайте команду:\n\n"
    "<code>/broadcast Ваш текст для розсилки</code>\n\n"
    "Приклад:\n"
    "<code>/broadcast Завтра о 10:00 відбудеться важлива зустріч.</code>"
)

ADMIN_BANS_TEXT = (
    "🚫 <b>Бан / Розбан користувачів</b>\n\n"
    "Заблокувати користувача:\n"
    "<code>/ban USER_ID</code>\n\n"
    "Розблокувати користувача:\n"
    "<code>/unban USER_ID</code>\n\n"
    "Приклад:\n"
    "<code>/ban 123456789</code>"
)

ADMIN_PREMIUM_TEXT = (
    "💎 <b>Premium-керування</b>\n\n"
    "Видати premium на кількість днів:\n"
    "<code>/premium USER_ID DAYS</code>\n\n"
    "Видати premium безстроково:\n"
    "<code>/premium_forever USER_ID</code>\n\n"
    "Забрати premium:\n"
    "<code>/unpremium USER_ID</code>\n\n"
    "Перевірити premium-статус:\n"
    "<code>/premium_status USER_ID</code>\n\n"
    "Приклади:\n"
    "<code>/premium 123456789 30</code>\n"
    "<code>/premium_forever 123456789</code>"
)


def build_admin_limits_text() -> str:
    return (
        "⚙️ <b>Поточні Free-ліміти</b>\n\n"
        f"💬 Текстові повідомлення: <b>{FREE_DAILY_TEXT_MESSAGE_LIMIT}</b> / день\n"
        f"📄 Файли: <b>{FREE_DAILY_FILE_LIMIT}</b> / день\n"
        f"🖼 OCR: <b>{FREE_DAILY_OCR_LIMIT}</b> / день\n"
        f"🔗 Посилання: <b>{FREE_DAILY_LINK_LIMIT}</b> / день\n"
        f"📝 Короткі змісти: <b>{FREE_DAILY_SUMMARY_LIMIT}</b> / день\n\n"
        "Premium-користувачі та адміністратори зараз мають безліміт."
    )


def build_admin_stats_text(
    total_users: int,
    active_users: int,
    banned_users: int,
    free_users: int,
    premium_users: int,
    usage_totals: dict[str, int],
) -> str:
    return (
        "📊 <b>Статистика проєкту</b>\n\n"
        "👥 <b>Користувачі:</b>\n"
        f"Усього: <b>{total_users}</b>\n"
        f"Активні: <b>{active_users}</b>\n"
        f"Заблоковані: <b>{banned_users}</b>\n"
        f"Free: <b>{free_users}</b>\n"
        f"Premium: <b>{premium_users}</b>\n\n"
        "📈 <b>Використання сьогодні:</b>\n"
        f"💬 Текстові повідомлення: <b>{usage_totals['text_messages_processed']}</b>\n"
        f"📄 Файли: <b>{usage_totals['files_processed']}</b>\n"
        f"🖼 OCR: <b>{usage_totals['ocr_processed']}</b>\n"
        f"🔗 Посилання: <b>{usage_totals['links_processed']}</b>\n"
        f"📝 Короткі змісти: <b>{usage_totals['summaries_generated']}</b>"
    )


def build_admin_users_text(users: list[dict], limit: int = 15) -> str:
    if not users:
        return "👥 <b>Користувачів поки немає.</b>"

    parts = [
        "👥 <b>Останні користувачі</b>\n",
        f"Показано останні {min(len(users), limit)} з {len(users)}.\n"
    ]

    for index, user in enumerate(users[:limit], start=1):
        status = "🚫 banned" if user.get("is_banned") else "✅ active"
        plan = user.get("plan") or "free"
        username = user.get("username") or "N/A"
        full_name = user.get("full_name") or "N/A"
        last_activity = user.get("last_activity") or "N/A"

        parts.append(
            f"{index}. <b>{full_name}</b> ({username})\n"
            f"   ID: <code>{user['user_id']}</code>\n"
            f"   Статус: {status} | Тариф: {plan}\n"
            f"   Активність: {last_activity}"
        )

    parts.append(
        "\nПовний список користувачів можна отримати командою:\n"
        "<code>/users</code>"
    )

    return "\n\n".join(parts)