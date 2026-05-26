# Файл: handlers/errors.py

import logging

from aiogram import Router
from aiogram.types import ErrorEvent

from texts.messages import GENERIC_INTERNAL_ERROR_TEXT

router = Router()
logger = logging.getLogger(__name__)


@router.error()
async def global_error_handler(event: ErrorEvent) -> bool:
    """
    Глобальний обробник непередбачених помилок.
    Цей обробник буде викликатися для будь-яких помилок, які не були оброблені іншими обробниками.
    """
    logger.exception(
        "GlobalErrorHandler: непередбачена помилка під час обробки update",
        exc_info=event.exception
    )

    update = event.update

    try:
        if update.callback_query:
            await update.callback_query.answer(
                GENERIC_INTERNAL_ERROR_TEXT,
                show_alert=True
            )
            return True

        if update.message:
            await update.message.answer(GENERIC_INTERNAL_ERROR_TEXT)
            return True

    except Exception:
        logger.exception(
            "GlobalErrorHandler: не вдалося повідомити користувача про помилку"
        )

    return True