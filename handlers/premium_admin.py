# Файл: handlers/premium_admin.py

from aiogram import Router, types
from aiogram.filters import Command

from config import ADMIN_IDS
from services.usage_limits_service import (
    get_effective_plan_info,
    grant_premium,
    revoke_premium,
)
from texts.limits import (
    build_premium_granted_text,
    build_premium_revoked_text,
    build_premium_status_text,
)

router = Router()


def _is_admin(message: types.Message) -> bool:
    return bool(
        message.from_user
        and message.from_user.id in ADMIN_IDS
    )


def _parse_user_id(message: types.Message) -> int | None:
    if not message.text:
        return None

    parts = message.text.split()

    if len(parts) < 2:
        return None

    if not parts[1].isdigit():
        return None

    return int(parts[1])


def _parse_days(message: types.Message) -> int | None:
    if not message.text:
        return None

    parts = message.text.split()

    if len(parts) < 3:
        return None

    if not parts[2].isdigit():
        return None

    return int(parts[2])


@router.message(Command("premium"))
async def grant_premium_handler(message: types.Message) -> None:
    """
    /premium USER_ID DAYS

    Приклад:
    /premium 123456789 30
    """
    if not _is_admin(message):
        return

    user_id = _parse_user_id(message)
    days = _parse_days(message)

    if user_id is None or days is None:
        await message.answer(
            "❌ Використання: /premium USER_ID DAYS\n"
            "Наприклад: /premium 123456789 30"
        )
        return

    premium_until = await grant_premium(user_id=user_id, days=days)

    await message.answer(
        build_premium_granted_text(
            user_id=user_id,
            days=days,
            premium_until=premium_until
        )
    )


@router.message(Command("premium_forever"))
async def grant_premium_forever_handler(message: types.Message) -> None:
    """
    /premium_forever USER_ID
    """
    if not _is_admin(message):
        return

    user_id = _parse_user_id(message)

    if user_id is None:
        await message.answer(
            "❌ Використання: /premium_forever USER_ID"
        )
        return

    await grant_premium(user_id=user_id, days=None)

    await message.answer(
        build_premium_granted_text(
            user_id=user_id,
            days=None,
            premium_until=None
        )
    )


@router.message(Command("unpremium"))
async def revoke_premium_handler(message: types.Message) -> None:
    """
    /unpremium USER_ID
    """
    if not _is_admin(message):
        return

    user_id = _parse_user_id(message)

    if user_id is None:
        await message.answer("❌ Використання: /unpremium USER_ID")
        return

    await revoke_premium(user_id=user_id)

    await message.answer(build_premium_revoked_text(user_id))


@router.message(Command("premium_status"))
async def premium_status_handler(message: types.Message) -> None:
    """
    /premium_status USER_ID
    """
    if not _is_admin(message):
        return

    user_id = _parse_user_id(message)

    if user_id is None:
        await message.answer("❌ Використання: /premium_status USER_ID")
        return

    plan_info = await get_effective_plan_info(user_id)

    await message.answer(
        build_premium_status_text(
            user_id=user_id,
            plan_name=plan_info["plan"],
            premium_until=plan_info["premium_until"],
        )
    )