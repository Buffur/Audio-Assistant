# Файл: services/redis_client.py

import logging
from urllib.parse import urlsplit, urlunsplit

import redis.asyncio as redis

from config import REDIS_URL

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def _redact_redis_url(redis_url: str) -> str:
    """
    Приховує пароль у Redis URL перед записом у лог.
    """
    try:
        parsed = urlsplit(redis_url)
    except ValueError:
        return "<invalid Redis URL>"

    if not parsed.password or "@" not in parsed.netloc:
        return redis_url

    credentials, host = parsed.netloc.rsplit("@", 1)

    if ":" in credentials:
        username, _password = credentials.split(":", 1)
        safe_credentials = f"{username}:***"
    else:
        safe_credentials = "***"

    return urlunsplit(
        (
            parsed.scheme,
            f"{safe_credentials}@{host}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


async def get_redis_client() -> redis.Redis:
    """
    Повертає глобальний Redis-клієнт.

    decode_responses=True означає, що Redis буде повертати str,
    а не bytes. Це зручніше для JSON/session/rate-limit логіки.
    """
    global _redis_client

    if _redis_client is None:
        _redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True
        )

        logger.info("Redis client створено: %s", _redact_redis_url(REDIS_URL))

    return _redis_client


async def close_redis_client() -> None:
    """
    Коректно закриває Redis-з'єднання при завершенні бота.
    """
    global _redis_client

    if _redis_client is None:
        return

    await _redis_client.aclose()
    _redis_client = None

    logger.info("Redis client закрито.")


async def check_redis_connection() -> None:
    """
    Перевіряє доступність Redis при старті застосунку.
    """
    client = await get_redis_client()
    await client.ping()

    logger.info("Redis connection OK.")
