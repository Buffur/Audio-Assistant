# Файл: handlers/usage.py

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from services.usage_limits_service import get_user_usage_status
from texts.limits import build_usage_text

router = Router()


@router.message(Command("usage"))
async def usage_handler(message: Message) -> None:
    user_id = message.from_user.id

    status = await get_user_usage_status(user_id)

    text = build_usage_text(
        plan_name=status["plan"],
        premium_until=status["premium_until"],
        text_messages_used=status["text_messages_processed"],
        files_used=status["files_processed"],
        ocr_used=status["ocr_processed"],
        links_used=status["links_processed"],
        summaries_used=status["summaries_generated"],
        text_messages_limit=status["text_messages_limit"],
        files_limit=status["files_limit"],
        ocr_limit=status["ocr_limit"],
        links_limit=status["links_limit"],
        summaries_limit=status["summaries_limit"],
    )

    await message.answer(text, parse_mode="HTML")