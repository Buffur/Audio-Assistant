# Файл: texts/limits.py

TEXT_MESSAGE_LIMIT_REACHED_TEXT = (
    "🚫 Ви досягли денного ліміту на звичайні текстові повідомлення.\n\n"
    "Спробуйте завтра або зверніться до адміністратора для отримання premium-доступу."
)

FILE_LIMIT_REACHED_TEXT = (
    "🚫 Ви досягли денного ліміту на обробку файлів.\n\n"
    "Спробуйте завтра або зверніться до адміністратора для отримання premium-доступу."
)

OCR_LIMIT_REACHED_TEXT = (
    "🚫 Ви досягли денного ліміту на OCR-розпізнавання фото або зображень.\n\n"
    "Спробуйте завтра або зверніться до адміністратора для отримання premium-доступу."
)

LINK_LIMIT_REACHED_TEXT = (
    "🚫 Ви досягли денного ліміту на обробку посилань.\n\n"
    "Спробуйте завтра або зверніться до адміністратора для отримання premium-доступу."
)

SUMMARY_LIMIT_REACHED_TEXT = (
    "🚫 Ви досягли денного ліміту на створення коротких змістів.\n\n"
    "Спробуйте завтра або зверніться до адміністратора для отримання premium-доступу."
)


def _format_limit_value(value: int | None) -> str:
    if value is None:
        return "безліміт"

    return str(value)


def build_usage_text(
    plan_name: str,
    premium_until: str | None,
    text_messages_used: int,
    files_used: int,
    ocr_used: int,
    links_used: int,
    summaries_used: int,
    text_messages_limit: int | None,
    files_limit: int | None,
    ocr_limit: int | None,
    links_limit: int | None,
    summaries_limit: int | None,
) -> str:
    premium_text = premium_until if premium_until else "безстроково"

    if plan_name == "premium":
        plan_line = f"💎 Тариф: Premium до {premium_text}"
    else:
        plan_line = "🆓 Тариф: Free"

    return (
        "📊 <b>Ваше використання сьогодні:</b>\n\n"
        f"{plan_line}\n\n"
        f"💬 Текстові повідомлення: {text_messages_used} / {_format_limit_value(text_messages_limit)}\n"
        f"📄 Файли: {files_used} / {_format_limit_value(files_limit)}\n"
        f"🖼 OCR: {ocr_used} / {_format_limit_value(ocr_limit)}\n"
        f"🔗 Посилання: {links_used} / {_format_limit_value(links_limit)}\n"
        f"📝 Короткі змісти: {summaries_used} / {_format_limit_value(summaries_limit)}"
    )


def build_premium_granted_text(user_id: int, days: int | None, premium_until: str | None) -> str:
    if days is None:
        return f"✅ Користувачу {user_id} видано premium безстроково."

    return (
        f"✅ Користувачу {user_id} видано premium на {days} днів.\n"
        f"Діє до: {premium_until}"
    )


def build_premium_revoked_text(user_id: int) -> str:
    return f"✅ Premium у користувача {user_id} скасовано."


def build_premium_status_text(
    user_id: int,
    plan_name: str,
    premium_until: str | None
) -> str:
    if plan_name == "premium":
        return (
            f"💎 Користувач {user_id}: Premium\n"
            f"Діє до: {premium_until or 'безстроково'}"
        )

    return f"🆓 Користувач {user_id}: Free"


def get_limit_reached_text(usage_type: str) -> str:
    if usage_type == "text":
        return TEXT_MESSAGE_LIMIT_REACHED_TEXT

    if usage_type == "file":
        return FILE_LIMIT_REACHED_TEXT

    if usage_type == "ocr":
        return OCR_LIMIT_REACHED_TEXT

    if usage_type == "link":
        return LINK_LIMIT_REACHED_TEXT

    return TEXT_MESSAGE_LIMIT_REACHED_TEXT