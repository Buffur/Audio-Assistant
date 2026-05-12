# Файл: bot.py

import asyncio
import importlib
import logging
from contextlib import suppress
from types import ModuleType

from aiogram import Bot, Dispatcher

from config import BOT_TOKEN
from database.db import init_db


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)


# ============================================================
# OPTIONAL IMPORTS
# ============================================================

try:
    from middlewares.user_activity import UserActivityMiddleware
except ImportError:
    UserActivityMiddleware = None
    logger.warning("middlewares.user_activity не знайдено. Глобальна реєстрація користувачів не підключена.")


try:
    from middlewares.ban import BanMiddleware
except ImportError:
    BanMiddleware = None
    logger.warning("middlewares.ban не знайдено. Глобальна перевірка бану не підключена.")


try:
    from middlewares.rate_limit import RateLimitMiddleware
except ImportError:
    RateLimitMiddleware = None
    logger.warning("middlewares.rate_limit не знайдено. Rate limit не підключено.")


try:
    from services.parser import close_http_session
except ImportError:
    close_http_session = None


try:
    from services.reading_session_store import (
        cleanup_all_reading_sessions,
        cleanup_expired_reading_sessions,
    )
except ImportError:
    cleanup_all_reading_sessions = None
    cleanup_expired_reading_sessions = None
    logger.warning(
        "services.reading_session_store не має cleanup-функцій. "
        "Фонове очищення reading-сесій не підключено."
    )


# ============================================================
# ROUTERS ORDER
# ============================================================

ROUTERS_ORDER = [
    # Глобальні помилки
    ("handlers.errors", False),

    # Адмінські handlers
    ("handlers.admin", True),
    ("handlers.admin_menu", False),
    ("handlers.premium_admin", False),

    # Користувацькі handlers
    ("handlers.start", True),
    ("handlers.settings", True),
    ("handlers.usage", False),
    ("handlers.history", False),
    ("handlers.catalog", False),
    ("handlers.reading_callbacks", False),

    # messages.router завжди останній,
    # бо він ловить усі звичайні повідомлення.
    ("handlers.messages", True),
]


# ============================================================
# BACKGROUND TASKS
# ============================================================

async def reading_session_cleanup_worker() -> None:
    """
    Фонове очищення застарілих reading-сесій.

    Потрібно, щоб сесії не залишались у пам'яті,
    якщо користувач почав читання, але не натиснув "Закінчити".
    """
    if cleanup_expired_reading_sessions is None:
        return

    while True:
        await asyncio.sleep(300)

        try:
            cleaned_count = await cleanup_expired_reading_sessions()

            if cleaned_count:
                logger.info(
                    "Очищено застарілих reading-сесій: %s",
                    cleaned_count
                )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Помилка під час фонового очищення reading-сесій"
            )


# ============================================================
# ROUTERS
# ============================================================

def _import_router_module(
    module_path: str,
    required: bool
) -> ModuleType | None:
    """
    Імпортує handler-модуль.

    required=True:
        якщо модуль не імпортується — бот має впасти,
        бо без нього основна робота некоректна.

    required=False:
        якщо модуля немає — просто пропускаємо.
        Це дозволяє підключати нові можливості поступово.
    """
    try:
        return importlib.import_module(module_path)

    except ImportError:
        if required:
            logger.exception(
                "Критичний handler не імпортовано: %s",
                module_path
            )
            raise

        logger.warning(
            "Опціональний handler пропущено: %s",
            module_path
        )
        return None


def include_project_routers(dp: Dispatcher) -> None:
    """
    Підключає всі handlers у правильному порядку.
    """
    for module_path, required in ROUTERS_ORDER:
        module = _import_router_module(
            module_path=module_path,
            required=required
        )

        if module is None:
            continue

        router = getattr(module, "router", None)

        if router is None:
            message = f"У модулі {module_path} немає router."

            if required:
                raise RuntimeError(message)

            logger.warning(message)
            continue

        dp.include_router(router)
        logger.info("Підключено router: %s", module_path)


# ============================================================
# MIDDLEWARES
# ============================================================

def setup_middlewares(dp: Dispatcher) -> None:
    """
    Підключає middleware.

    Порядок важливий:
    1. UserActivityMiddleware — реєстрація / оновлення користувача;
    2. BanMiddleware — глобальна перевірка бану;
    3. RateLimitMiddleware — захист від spam/flood.
    """
    if UserActivityMiddleware is not None:
        user_activity_middleware = UserActivityMiddleware()

        dp.message.middleware(user_activity_middleware)
        dp.callback_query.middleware(user_activity_middleware)

        logger.info("Підключено UserActivityMiddleware")

    if BanMiddleware is not None:
        ban_middleware = BanMiddleware()

        dp.message.middleware(ban_middleware)
        dp.callback_query.middleware(ban_middleware)

        logger.info("Підключено BanMiddleware")

    if RateLimitMiddleware is not None:
        rate_limit_middleware = RateLimitMiddleware(
            max_events=8,
            period_seconds=10,
            warning_cooldown_seconds=10
        )

        dp.message.middleware(rate_limit_middleware)
        dp.callback_query.middleware(rate_limit_middleware)

        logger.info("Підключено RateLimitMiddleware")


# ============================================================
# MAIN
# ============================================================

async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    cleanup_task: asyncio.Task | None = None

    await init_db()

    setup_middlewares(dp)
    include_project_routers(dp)

    if cleanup_expired_reading_sessions is not None:
        cleanup_task = asyncio.create_task(
            reading_session_cleanup_worker()
        )
        logger.info("Фонове очищення reading-сесій запущено.")

    logger.info("Бот запущено.")

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )

    finally:
        if cleanup_task is not None:
            cleanup_task.cancel()

            with suppress(asyncio.CancelledError):
                await cleanup_task

        if cleanup_all_reading_sessions is not None:
            await cleanup_all_reading_sessions()

        if close_http_session is not None:
            await close_http_session()

        await bot.session.close()

        logger.info("Бот зупинено.")


if __name__ == "__main__":
    asyncio.run(main())