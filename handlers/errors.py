# Файл: handlers/errors.py

import logging
from typing import Any

from aiogram import Router
from aiogram.types import ErrorEvent

from services.runtime_state import record_runtime_error
from services.telemetry_service import record_service_metric
from texts.messages import GENERIC_INTERNAL_ERROR_TEXT

router = Router()
logger = logging.getLogger(__name__)


def _exception_info(error: Exception) -> tuple[type[BaseException], BaseException, Any]:
    return (type(error), error, error.__traceback__)


def _callback_data_prefix(callback_data: str | None) -> str | None:
    if not callback_data:
        return None

    return callback_data.split(":", 1)[0][:64]


def _build_error_context(event: ErrorEvent) -> dict[str, Any]:
    update = event.update
    callback_query = getattr(update, "callback_query", None)
    message = getattr(update, "message", None)

    if callback_query is not None and message is None:
        message = getattr(callback_query, "message", None)

    user = getattr(callback_query, "from_user", None) or getattr(
        message,
        "from_user",
        None,
    )
    chat = getattr(message, "chat", None)
    callback_data = getattr(callback_query, "data", None)

    if callback_query is not None:
        update_type = "callback_query"
    elif message is not None:
        update_type = "message"
    else:
        update_type = "unknown"

    return {
        "telegram_update_id": getattr(update, "update_id", None),
        "telegram_update_type": update_type,
        "telegram_user_id": getattr(user, "id", None),
        "telegram_chat_id": getattr(chat, "id", None),
        "telegram_message_id": getattr(message, "message_id", None),
        "telegram_callback_prefix": _callback_data_prefix(callback_data),
        "telegram_callback_data_length": (
            len(callback_data) if callback_data else 0
        ),
    }


async def _record_unhandled_update_error(event: ErrorEvent) -> None:
    record_runtime_error("telegram_update", event.exception)

    try:
        await record_service_metric(
            provider="bot",
            operation="update_handler",
            success=False,
            latency_ms=0,
            error=event.exception,
        )
    except Exception:
        logger.exception("GlobalErrorHandler: failed to record error metric")


@router.error()
async def global_error_handler(event: ErrorEvent) -> bool:
    """
    Глобальний обробник непередбачених помилок.
    Цей обробник буде викликатися для будь-яких помилок, які не були оброблені іншими обробниками.
    """
    logger.exception(
        "GlobalErrorHandler: непередбачена помилка під час обробки update",
        exc_info=_exception_info(event.exception),
        extra=_build_error_context(event),
    )
    await _record_unhandled_update_error(event)

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
