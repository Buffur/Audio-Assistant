# Файл: bot.py

import asyncio
import importlib
import logging
from contextlib import suppress
from types import ModuleType
from typing import Any

from aiogram import Bot, Dispatcher  # type: ignore

from config import BOT_TOKEN
from database.db import init_db

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# IMPORT HELPERS
# ============================================================

def _is_missing_target_module(error: ModuleNotFoundError, module_path: str) -> bool:
    """
    Перевіряє, чи помилка означає саме відсутність потрібного модуля,
    а не відсутність залежності всередині цього модуля.
    """
    missing_name = error.name

    if not missing_name:
        return False

    return missing_name == module_path or module_path.startswith(f"{missing_name}.")


def _import_optional_attr(
    module_path: str,
    attr_name: str,
    warning_message: str,
) -> Any | None:
    """
    Імпортує атрибут з опціонального модуля.

    Якщо самого модуля немає — повертає None.
    Якщо модуль існує, але всередині нього зламався імпорт — кидає помилку.
    Якщо атрибута немає — повертає None і пише warning.
    """
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as error:
        if _is_missing_target_module(error, module_path):
            logger.warning(warning_message)
            return None

        logger.exception(
            "Помилка залежності під час імпорту опціонального модуля: %s",
            module_path,
        )
        raise

    attr = getattr(module, attr_name, None)

    if attr is None:
        logger.warning(
            "У модулі %s не знайдено атрибут %s. %s",
            module_path,
            attr_name,
            warning_message,
        )
        return None

    return attr


# ============================================================
# OPTIONAL IMPORTS
# ============================================================

UserActivityMiddleware = _import_optional_attr(
    module_path="middlewares.user_activity",
    attr_name="UserActivityMiddleware",
    warning_message=(
        "middlewares.user_activity не знайдено. "
        "Глобальна реєстрація користувачів не підключена."
    ),
)

BanMiddleware = _import_optional_attr(
    module_path="middlewares.ban",
    attr_name="BanMiddleware",
    warning_message=(
        "middlewares.ban не знайдено. "
        "Глобальна перевірка бану не підключена."
    ),
)

RateLimitMiddleware = _import_optional_attr(
    module_path="middlewares.rate_limit",
    attr_name="RateLimitMiddleware",
    warning_message=(
        "middlewares.rate_limit не знайдено. "
        "Rate limit не підключено."
    ),
)

close_http_session = _import_optional_attr(
    module_path="services.parser",
    attr_name="close_http_session",
    warning_message=(
        "services.parser або close_http_session не знайдено. "
        "Закриття HTTP-сесії парсера не підключено."
    ),
)

cleanup_all_reading_sessions = _import_optional_attr(
    module_path="services.reading_session_store",
    attr_name="cleanup_all_reading_sessions",
    warning_message=(
        "services.reading_session_store не має cleanup_all_reading_sessions. "
        "Повне очищення reading-сесій не підключено."
    ),
)

cleanup_expired_reading_sessions = _import_optional_attr(
    module_path="services.reading_session_store",
    attr_name="cleanup_expired_reading_sessions",
    warning_message=(
        "services.reading_session_store не має cleanup_expired_reading_sessions. "
        "Фонове очищення reading-сесій не підключено."
    ),
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

    Потрібно, щоб сесії не залишались у пам'яті, якщо користувач
    почав читання, але не натиснув "Закінчити".
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
                    cleaned_count,
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
    required: bool,
) -> ModuleType | None:
    """
    Імпортує handler-модуль.

    required=True:
        якщо модуль не імпортується — бот має впасти,
        бо без нього основна робота некоректна.

    required=False:
        якщо самого модуля немає — просто пропускаємо.
        Якщо модуль існує, але всередині нього зламався імпорт —
        помилка не приховується.
    """
    try:
        return importlib.import_module(module_path)

    except ModuleNotFoundError as error:
        if required:
            logger.exception(
                "Критичний handler не імпортовано: %s",
                module_path,
            )
            raise

        if _is_missing_target_module(error, module_path):
            logger.warning(
                "Опціональний handler пропущено: %s",
                module_path,
            )
            return None

        logger.exception(
            "Помилка залежності під час імпорту handler: %s",
            module_path,
        )
        raise


def include_project_routers(dp: Dispatcher) -> None:
    """
    Підключає всі handlers у правильному порядку.
    """
    for module_path, required in ROUTERS_ORDER:
        module = _import_router_module(
            module_path=module_path,
            required=required,
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
            warning_cooldown_seconds=10,
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
            allowed_updates=dp.resolve_used_update_types(),
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