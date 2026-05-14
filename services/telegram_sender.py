# Файл: services/telegram_sender.py

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

logger = logging.getLogger(__name__)

DEFAULT_SEND_DELAY_SECONDS = 0.05
DEFAULT_RETRY_ATTEMPTS = 2


async def sleep_after_send(delay_seconds: float = DEFAULT_SEND_DELAY_SECONDS) -> None:
    if delay_seconds <= 0:
        return

    await asyncio.sleep(delay_seconds)


async def _send_with_retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    context: str,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
) -> Any | None:
    retry_attempts = max(retry_attempts, 1)

    for attempt in range(1, retry_attempts + 1):
        try:
            return await operation()

        except TelegramRetryAfter as error:
            logger.warning(
                "TelegramSender: rate limit context=%s attempt=%s/%s retry_after=%s",
                context,
                attempt,
                retry_attempts,
                error.retry_after,
            )

            if attempt >= retry_attempts:
                return None

            await asyncio.sleep(error.retry_after)

        except TelegramForbiddenError:
            logger.warning(
                "TelegramSender: користувач недоступний або заблокував бота context=%s",
                context,
            )
            return None

        except TelegramBadRequest:
            logger.exception(
                "TelegramSender: некоректний Telegram-запит context=%s",
                context,
            )
            return None

        except TelegramAPIError:
            logger.exception(
                "TelegramSender: Telegram API error context=%s",
                context,
            )
            return None

        except Exception:
            logger.exception(
                "TelegramSender: несподівана помилка надсилання context=%s",
                context,
            )
            return None

    return None


async def safe_answer_voice(
    *,
    message,
    voice,
    caption: str | None = None,
    reply_markup=None,
    delay_seconds: float = 0,
) -> Any | None:
    sent_message = await _send_with_retry(
        lambda: message.answer_voice(
            voice,
            caption=caption,
            reply_markup=reply_markup,
        ),
        context=f"answer_voice chat_id={getattr(getattr(message, 'chat', None), 'id', None)}",
    )

    await sleep_after_send(delay_seconds)

    return sent_message


async def safe_send_voice(
    *,
    bot,
    chat_id: int,
    voice,
    caption: str | None = None,
    reply_markup=None,
    delay_seconds: float = 0,
) -> Any | None:
    sent_message = await _send_with_retry(
        lambda: bot.send_voice(
            chat_id=chat_id,
            voice=voice,
            caption=caption,
            reply_markup=reply_markup,
        ),
        context=f"send_voice chat_id={chat_id}",
    )

    await sleep_after_send(delay_seconds)

    return sent_message
