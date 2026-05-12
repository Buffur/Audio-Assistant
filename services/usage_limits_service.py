# Файл: services/usage_limits_service.py

from datetime import datetime, timedelta

from aiogram import types

from config import (
    ADMIN_IDS,
    FREE_DAILY_FILE_LIMIT,
    FREE_DAILY_LINK_LIMIT,
    FREE_DAILY_OCR_LIMIT,
    FREE_DAILY_SUMMARY_LIMIT,
    FREE_DAILY_TEXT_MESSAGE_LIMIT,
)
from database.db import (
    get_daily_usage,
    get_user_plan_info,
    increment_daily_usage,
    revoke_user_premium,
    set_user_premium,
    try_increment_daily_usage_under_limit,
)

USAGE_TYPE_TEXT = "text"
USAGE_TYPE_FILE = "file"
USAGE_TYPE_OCR = "ocr"
USAGE_TYPE_LINK = "link"

USAGE_FIELD_TEXT_MESSAGES = "text_messages_processed"
USAGE_FIELD_FILES = "files_processed"
USAGE_FIELD_OCR = "ocr_processed"
USAGE_FIELD_LINKS = "links_processed"
USAGE_FIELD_SUMMARIES = "summaries_generated"


def _today_key() -> str:
    return datetime.now().date().isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _message_has_link(message: types.Message) -> bool:
    if not message.text:
        return False

    return "http://" in message.text or "https://" in message.text


def _is_image_document(message: types.Message) -> bool:
    if not message.document:
        return False

    mime_type = message.document.mime_type or ""
    return mime_type.startswith("image/")


def detect_input_usage_type(message: types.Message) -> str:
    """
    Визначає, який саме денний ліміт треба застосувати.

    text -> великий ліміт
    link -> ліміт посилань
    photo/image document -> OCR ліміт
    document -> файловий ліміт
    """
    if message.photo:
        return USAGE_TYPE_OCR

    if _is_image_document(message):
        return USAGE_TYPE_OCR

    if message.document:
        return USAGE_TYPE_FILE

    if _message_has_link(message):
        return USAGE_TYPE_LINK

    return USAGE_TYPE_TEXT


def _usage_field_for_type(usage_type: str) -> str:
    if usage_type == USAGE_TYPE_TEXT:
        return USAGE_FIELD_TEXT_MESSAGES

    if usage_type == USAGE_TYPE_FILE:
        return USAGE_FIELD_FILES

    if usage_type == USAGE_TYPE_OCR:
        return USAGE_FIELD_OCR

    if usage_type == USAGE_TYPE_LINK:
        return USAGE_FIELD_LINKS

    return USAGE_FIELD_TEXT_MESSAGES


def _usage_limit_for_type(
    usage_type: str,
    limits: dict[str, int | None],
) -> int | None:
    if usage_type == USAGE_TYPE_TEXT:
        return limits["text_messages_limit"]

    if usage_type == USAGE_TYPE_FILE:
        return limits["files_limit"]

    if usage_type == USAGE_TYPE_OCR:
        return limits["ocr_limit"]

    if usage_type == USAGE_TYPE_LINK:
        return limits["links_limit"]

    return limits["text_messages_limit"]


async def is_premium_user(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True

    plan_info = await get_user_plan_info(user_id)

    if plan_info["plan"] != "premium":
        return False

    premium_until = _parse_datetime(plan_info.get("premium_until"))

    if premium_until is None:
        return True

    return premium_until > datetime.now()


async def get_effective_plan_info(user_id: int) -> dict:
    if user_id in ADMIN_IDS:
        return {
            "plan": "premium",
            "premium_until": None,
            "is_premium": True,
        }

    plan_info = await get_user_plan_info(user_id)
    is_premium = await is_premium_user(user_id)

    return {
        "plan": "premium" if is_premium else "free",
        "premium_until": plan_info.get("premium_until") if is_premium else None,
        "is_premium": is_premium,
    }


def _get_limits_for_plan(is_premium: bool) -> dict[str, int | None]:
    if is_premium:
        return {
            "text_messages_limit": None,
            "files_limit": None,
            "ocr_limit": None,
            "links_limit": None,
            "summaries_limit": None,
        }

    return {
        "text_messages_limit": FREE_DAILY_TEXT_MESSAGE_LIMIT,
        "files_limit": FREE_DAILY_FILE_LIMIT,
        "ocr_limit": FREE_DAILY_OCR_LIMIT,
        "links_limit": FREE_DAILY_LINK_LIMIT,
        "summaries_limit": FREE_DAILY_SUMMARY_LIMIT,
    }


async def get_user_usage_status(user_id: int) -> dict:
    usage_date = _today_key()
    usage = await get_daily_usage(user_id, usage_date)
    plan_info = await get_effective_plan_info(user_id)
    limits = _get_limits_for_plan(plan_info["is_premium"])

    return {
        **usage,
        **plan_info,
        **limits,
    }


def _is_under_limit(current_value: int, limit: int | None) -> bool:
    if limit is None:
        return True

    return current_value < limit


async def can_process_input(
    user_id: int,
    usage_type: str,
) -> bool:
    """
    Тільки перевіряє ліміт без списання.

    Для реальної обробки повідомлень краще використовувати
    reserve_input_processing(), щоб перевірка і списання були одним кроком.
    """
    status = await get_user_usage_status(user_id)

    if usage_type == USAGE_TYPE_TEXT:
        return _is_under_limit(
            status["text_messages_processed"],
            status["text_messages_limit"],
        )

    if usage_type == USAGE_TYPE_FILE:
        return _is_under_limit(
            status["files_processed"],
            status["files_limit"],
        )

    if usage_type == USAGE_TYPE_OCR:
        return _is_under_limit(
            status["ocr_processed"],
            status["ocr_limit"],
        )

    if usage_type == USAGE_TYPE_LINK:
        return _is_under_limit(
            status["links_processed"],
            status["links_limit"],
        )

    return _is_under_limit(
        status["text_messages_processed"],
        status["text_messages_limit"],
    )


async def record_input_processed(
    user_id: int,
    usage_type: str,
) -> None:
    await increment_daily_usage(
        user_id=user_id,
        usage_date=_today_key(),
        field_name=_usage_field_for_type(usage_type),
    )


async def reserve_input_processing(
    user_id: int,
    usage_type: str,
) -> bool:
    """
    Резервує денний ліміт перед важкою обробкою.

    Для free-користувачів:
    - атомарно перевіряє ліміт;
    - якщо ліміт ще є — одразу списує 1 використання;
    - якщо ліміт вичерпано — повертає False.

    Для premium/admin:
    - ліміт безмежний;
    - usage все одно записується для статистики.
    """
    usage_date = _today_key()
    usage_field = _usage_field_for_type(usage_type)
    premium = await is_premium_user(user_id)

    if premium:
        await increment_daily_usage(
            user_id=user_id,
            usage_date=usage_date,
            field_name=usage_field,
        )
        return True

    limits = _get_limits_for_plan(is_premium=False)
    limit = _usage_limit_for_type(usage_type, limits)

    return await try_increment_daily_usage_under_limit(
        user_id=user_id,
        usage_date=usage_date,
        field_name=usage_field,
        limit=limit,
    )


async def can_generate_summary(user_id: int) -> bool:
    """
    Тільки перевіряє summary-ліміт без списання.

    Для реальної генерації короткого змісту краще використовувати
    reserve_summary_generation().
    """
    status = await get_user_usage_status(user_id)

    return _is_under_limit(
        status["summaries_generated"],
        status["summaries_limit"],
    )


async def record_summary_generated(user_id: int) -> None:
    await increment_daily_usage(
        user_id=user_id,
        usage_date=_today_key(),
        field_name=USAGE_FIELD_SUMMARIES,
    )


async def reserve_summary_generation(user_id: int) -> bool:
    """
    Резервує денний summary-ліміт перед AI/TTS генерацією.

    Для free-користувачів:
    - атомарно перевіряє summaries_generated;
    - якщо ліміт ще є — одразу списує 1 використання;
    - якщо ліміт вичерпано — повертає False.

    Для premium/admin:
    - ліміт безмежний;
    - usage все одно записується для статистики.
    """
    usage_date = _today_key()
    premium = await is_premium_user(user_id)

    if premium:
        await increment_daily_usage(
            user_id=user_id,
            usage_date=usage_date,
            field_name=USAGE_FIELD_SUMMARIES,
        )
        return True

    limits = _get_limits_for_plan(is_premium=False)
    limit = limits["summaries_limit"]

    return await try_increment_daily_usage_under_limit(
        user_id=user_id,
        usage_date=usage_date,
        field_name=USAGE_FIELD_SUMMARIES,
        limit=limit,
    )


async def grant_premium(user_id: int, days: int | None = None) -> str | None:
    if days is None:
        await set_user_premium(user_id=user_id, premium_until=None)
        return None

    premium_until = datetime.now() + timedelta(days=days)
    premium_until_text = premium_until.isoformat(timespec="seconds")

    await set_user_premium(
        user_id=user_id,
        premium_until=premium_until_text,
    )

    return premium_until_text


async def revoke_premium(user_id: int) -> None:
    await revoke_user_premium(user_id)