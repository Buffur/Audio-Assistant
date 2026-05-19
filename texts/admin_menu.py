# Файл: texts/admin_menu.py

import html

ADMIN_ACCESS_DENIED_TEXT = "🚫 У вас немає доступу до адмін-меню."

ADMIN_MENU_TEXT = (
    "🛠 <b>Адмін-меню</b>\n\n"
    "Оберіть потрібний розділ:"
)

ADMIN_BROADCAST_TEXT = (
    "📢 <b>Розсилка</b>\n\n"
    "Щоб підготувати голосову розсилку всім активним користувачам, використайте команду:\n\n"
    "<code>/broadcast Ваш текст для розсилки</code>\n\n"
    "Бот покаже preview і попросить підтвердження перед відправленням.\n\n"
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
    "💎 <b>Керування Ліміт+</b>\n\n"
    "Видати Ліміт+ на кількість днів:\n"
    "<code>/premium USER_ID DAYS</code>\n\n"
    "Видати Ліміт+ безстроково:\n"
    "<code>/premium_forever USER_ID</code>\n\n"
    "Забрати Ліміт+:\n"
    "<code>/unpremium USER_ID</code>\n\n"
    "Перевірити статус Ліміт+:\n"
    "<code>/premium_status USER_ID</code>\n\n"
    "Приклади:\n"
    "<code>/premium 123456789 30</code>\n"
    "<code>/premium_forever 123456789</code>"
)


ADMIN_LIMIT_LABELS = {
    "text_messages_limit": "Текстові повідомлення",
    "files_limit": "Файли",
    "ocr_limit": "Фотографії",
    "links_limit": "Посилання",
    "summaries_limit": "Короткі змісти",
}

ADMIN_LIMIT_ICONS = {
    "text_messages_limit": "💬",
    "files_limit": "📄",
    "ocr_limit": "🖼",
    "links_limit": "🔗",
    "summaries_limit": "📝",
}

ADMIN_USER_ACTION_LABELS = {
    "ban": "заблокувати користувача",
    "unban": "розблокувати користувача",
    "limit_plus_30": "видати Ліміт+ на 30 днів",
    "limit_plus_forever": "видати Ліміт+ безстроково",
    "limit_plus_revoke": "зняти Ліміт+",
}


def build_admin_limits_text(limits: dict[str, int]) -> str:
    return (
        "⚙️ <b>Поточні ліміти</b>\n\n"
        f"💬 Текстові повідомлення: <b>{limits['text_messages_limit']}</b> / день\n"
        f"📄 Файли: <b>{limits['files_limit']}</b> / день\n"
        f"🖼 Фотографії: <b>{limits['ocr_limit']}</b> / день\n"
        f"🔗 Посилання: <b>{limits['links_limit']}</b> / день\n"
        f"📝 Короткі змісти: <b>{limits['summaries_limit']}</b> / день\n\n"
        "Оберіть ліміт кнопкою нижче, щоб змінити значення.\n\n"
        "Користувачі з Ліміт+ та адміністратори зараз мають безліміт."
    )


def build_admin_limit_edit_text(
    limit_name: str,
    current_value: int,
    default_value: int,
) -> str:
    label = ADMIN_LIMIT_LABELS.get(limit_name, limit_name)
    icon = ADMIN_LIMIT_ICONS.get(limit_name, "⚙️")

    return (
        f"{icon} <b>{label}</b>\n\n"
        f"Поточне значення: <b>{current_value}</b> / день\n"
        f"Значення за замовчуванням: <b>{default_value}</b> / день\n\n"
        "Змініть значення кнопками нижче."
    )


SERVICE_PROVIDER_LABELS = {
    "edge": "Edge TTS",
    "gemini": "Gemini",
    "piper": "Piper",
}

SERVICE_OPERATION_LABELS = {
    "ocr": "фотографії",
    "parser": "парсинг",
    "tts": "TTS",
}


def _format_money(value: float) -> str:
    return f"${value:.4f}"


def _format_service_metrics(service_metrics: dict | None) -> str:
    if not service_metrics or not service_metrics.get("total_requests"):
        return (
            "\n\n🔎 <b>Зовнішні сервіси за 24 год:</b>\n"
            "Поки немає записаних запитів."
        )

    groups = service_metrics.get("groups", [])
    parts = [
        "\n\n🔎 <b>Зовнішні сервіси за 24 год:</b>",
        (
            f"Запитів: <b>{service_metrics['total_requests']}</b> | "
            f"помилок: <b>{service_metrics['total_errors']}</b>"
        ),
        (
            f"Latency avg/max: <b>{service_metrics['avg_latency_ms']} ms</b> / "
            f"<b>{service_metrics['max_latency_ms']} ms</b>"
        ),
        f"Оцінка витрат: <b>{_format_money(service_metrics['estimated_cost_usd'])}</b>",
    ]

    for group in groups[:6]:
        provider = SERVICE_PROVIDER_LABELS.get(
            str(group.get("provider") or ""),
            str(group.get("provider") or "unknown"),
        )
        operation = SERVICE_OPERATION_LABELS.get(
            str(group.get("operation") or ""),
            str(group.get("operation") or "unknown"),
        )
        parts.append(
            f"• {html.escape(provider)} / {html.escape(operation)}: "
            f"{group['requests']} req, {group['errors']} err, "
            f"avg {group['avg_latency_ms']} ms, "
            f"{_format_money(group['estimated_cost_usd'])}"
        )

    return "\n".join(parts)


def build_admin_stats_text(
    total_users: int,
    active_users: int,
    banned_users: int,
    free_users: int,
    premium_users: int,
    usage_totals: dict[str, int],
    service_metrics: dict | None = None,
) -> str:
    text = (
        "📊 <b>Статистика проєкту</b>\n\n"
        "👥 <b>Користувачі:</b>\n"
        f"Усього: <b>{total_users}</b>\n"
        f"Активні: <b>{active_users}</b>\n"
        f"Заблоковані: <b>{banned_users}</b>\n"
        f"Ліміт: <b>{free_users}</b>\n"
        f"Ліміт+: <b>{premium_users}</b>\n\n"
        "📈 <b>Використання сьогодні:</b>\n"
        f"💬 Текстові повідомлення: <b>{usage_totals['text_messages_processed']}</b>\n"
        f"📄 Файли: <b>{usage_totals['files_processed']}</b>\n"
        f"🖼 Фотографії: <b>{usage_totals['ocr_processed']}</b>\n"
        f"🔗 Посилання: <b>{usage_totals['links_processed']}</b>\n"
        f"📝 Короткі змісти: <b>{usage_totals['summaries_generated']}</b>"
    )

    return text + _format_service_metrics(service_metrics)


def build_admin_users_text(
    users: list[dict],
    page: int = 0,
    page_size: int = 10,
) -> str:
    if not users:
        return "👥 <b>Користувачів поки немає.</b>"

    page = max(page, 0)
    total_pages = max((len(users) + page_size - 1) // page_size, 1)
    page = min(page, total_pages - 1)
    start_index = page * page_size
    page_users = users[start_index:start_index + page_size]

    parts = [
        "👥 <b>Останні користувачі</b>\n",
        f"Сторінка {page + 1} з {total_pages}. "
        f"Показано {len(page_users)} з {len(users)}.\n"
    ]

    for index, user in enumerate(page_users, start=start_index + 1):
        status = "🚫 banned" if user.get("is_banned") else "✅ active"
        plan = "Ліміт+" if user.get("plan") == "premium" else "Ліміт"
        username = html.escape(str(user.get("username") or "N/A"))
        full_name = html.escape(str(user.get("full_name") or "N/A"))
        last_activity = html.escape(str(user.get("last_activity") or "N/A"))

        parts.append(
            f"{index}. <b>{full_name}</b> ({username})\n"
            f"   ID: <code>{user['user_id']}</code>\n"
            f"   Статус: {status} | Тариф: {plan}\n"
            f"   Активність: {last_activity}"
        )

    parts.append(
        "\nОберіть користувача кнопкою нижче, щоб відкрити дії."
    )

    return "\n\n".join(parts)


def build_admin_user_detail_text(user: dict) -> str:
    status = "🚫 заблокований" if user.get("is_banned") else "✅ активний"
    plan = "Ліміт+" if user.get("plan") == "premium" else "Ліміт"
    premium_until = user.get("premium_until") or "безстроково"
    username = html.escape(str(user.get("username") or "N/A"))
    full_name = html.escape(str(user.get("full_name") or "N/A"))
    last_activity = html.escape(str(user.get("last_activity") or "N/A"))

    plan_line = plan

    if user.get("plan") == "premium":
        plan_line = f"{plan} до {html.escape(str(premium_until))}"

    return (
        "👤 <b>Користувач</b>\n\n"
        f"Ім'я: <b>{full_name}</b>\n"
        f"Username: {username}\n"
        f"ID: <code>{user['user_id']}</code>\n"
        f"Статус: {status}\n"
        f"Тариф: {plan_line}\n"
        f"Активність: {last_activity}"
    )


def build_admin_user_action_confirm_text(action: str, user: dict) -> str:
    action_label = ADMIN_USER_ACTION_LABELS.get(action, action)
    username = html.escape(str(user.get("username") or "N/A"))
    full_name = html.escape(str(user.get("full_name") or "N/A"))

    return (
        "⚠️ <b>Підтвердження дії</b>\n\n"
        f"Дія: <b>{html.escape(action_label)}</b>\n"
        f"Користувач: <b>{full_name}</b> ({username})\n"
        f"ID: <code>{user['user_id']}</code>\n\n"
        "Підтвердьте дію кнопкою нижче."
    )
