# Файл: bot.py

import asyncio
import importlib
import logging
from contextlib import suppress
from types import ModuleType
from typing import Any

from aiogram import Bot, Dispatcher  # type: ignore
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from config import (
    ADMIN_IDS,
    API_ENABLED,
    API_HOST,
    API_PORT,
    BOT_RUNTIME_MODE,
    BOT_TOKEN,
    CLEAR_KNOWN_USER_COMMANDS_ON_STARTUP,
    HIDE_USER_COMMANDS,
    LOG_FORMAT,
    LOG_LEVEL,
    LOG_SERVICE_NAME,
    MAINTENANCE_CLEANUP_INTERVAL_SECONDS,
    RATE_LIMIT_BACKEND,
    RATE_LIMIT_MAX_EVENTS,
    RATE_LIMIT_PERIOD_SECONDS,
    RATE_LIMIT_WARNING_COOLDOWN_SECONDS,
    TELEGRAM_WEBHOOK_SECRET_TOKEN,
    TELEGRAM_WEBHOOK_URL,
)
from database.db import get_all_users, init_db
from services.logging_config import setup_logging

# ============================================================
# LOGGING
# ============================================================

setup_logging(
    level=LOG_LEVEL,
    log_format=LOG_FORMAT,
    service_name=LOG_SERVICE_NAME,
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

RedisRateLimitMiddleware = _import_optional_attr(
    module_path="middlewares.redis_rate_limit",
    attr_name="RedisRateLimitMiddleware",
    warning_message=(
        "middlewares.redis_rate_limit не знайдено. "
        "Redis rate limit не підключено."
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

close_redis_client = _import_optional_attr(
    module_path="services.redis_client",
    attr_name="close_redis_client",
    warning_message=(
        "services.redis_client або close_redis_client не знайдено. "
        "Закриття Redis-з'єднання не підключено."
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

close_reading_audio_queue = _import_optional_attr(
    module_path="services.reading_service",
    attr_name="close_reading_audio_queue",
    warning_message=(
        "services.reading_service не має close_reading_audio_queue. "
        "Фонову чергу озвучки не буде закрито явно."
    ),
)

start_reading_audio_workers = _import_optional_attr(
    module_path="services.reading_service",
    attr_name="start_reading_audio_workers",
    warning_message=(
        "services.reading_service не має start_reading_audio_workers. "
        "Redis audio workers не будуть запущені на startup."
    ),
)

run_maintenance_cleanup = _import_optional_attr(
    module_path="services.maintenance_service",
    attr_name="run_maintenance_cleanup",
    warning_message=(
        "services.maintenance_service не має run_maintenance_cleanup. "
        "Фонове очищення retention-даних не підключено."
    ),
)


close_telemetry_service = _import_optional_attr(
    module_path="services.telemetry_service",
    attr_name="close_telemetry_service",
    warning_message=(
        "services.telemetry_service or close_telemetry_service not found. "
        "Telemetry flush on shutdown is disabled."
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
    ("handlers.privacy", False),
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


async def maintenance_cleanup_worker() -> None:
    if run_maintenance_cleanup is None:
        return

    while True:
        try:
            await run_maintenance_cleanup()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Помилка під час фонового maintenance cleanup")

        await asyncio.sleep(MAINTENANCE_CLEANUP_INTERVAL_SECONDS)


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

    if RATE_LIMIT_BACKEND == "redis" and RedisRateLimitMiddleware is not None:
        rate_limit_middleware = RedisRateLimitMiddleware(
            max_events=RATE_LIMIT_MAX_EVENTS,
            period_seconds=RATE_LIMIT_PERIOD_SECONDS,
            warning_cooldown_seconds=RATE_LIMIT_WARNING_COOLDOWN_SECONDS,
        )
        dp.message.middleware(rate_limit_middleware)
        dp.callback_query.middleware(rate_limit_middleware)
        logger.info("Підключено RedisRateLimitMiddleware")
        return

    if RATE_LIMIT_BACKEND == "redis" and RedisRateLimitMiddleware is None:
        logger.warning(
            "RATE_LIMIT_BACKEND=redis, але RedisRateLimitMiddleware недоступний. "
            "Використовую in-memory RateLimitMiddleware."
        )

    if RateLimitMiddleware is not None:
        rate_limit_middleware = RateLimitMiddleware(
            max_events=RATE_LIMIT_MAX_EVENTS,
            period_seconds=RATE_LIMIT_PERIOD_SECONDS,
            warning_cooldown_seconds=RATE_LIMIT_WARNING_COOLDOWN_SECONDS,
        )
        dp.message.middleware(rate_limit_middleware)
        dp.callback_query.middleware(rate_limit_middleware)
        logger.info("Підключено RateLimitMiddleware")


# ============================================================
# BOT COMMANDS
# ============================================================

COMMAND_SETUP_TIMEOUT_SECONDS = 10
COMMAND_LANGUAGE_CODES_TO_CLEAR = ("uk", "ru", "en")

MINIMAL_USER_COMMANDS = [
    BotCommand(command="start", description="Почати роботу"),
    BotCommand(command="help", description="Показати довідку"),
    BotCommand(command="settings", description="Налаштувати голос і швидкість"),
    BotCommand(command="catalog", description="Каталог документів"),
    BotCommand(command="catalog_clear", description="Очистити каталог"),
    BotCommand(command="usage", description="Показати статистику використання"),
    BotCommand(command="privacy", description="Показати політику конфіденційності"),
    BotCommand(command="delete_my_data", description="Очищає вашу історію документів"),
]

USER_COMMANDS = [
    *MINIMAL_USER_COMMANDS,
    BotCommand(command="history", description="Показати історію документів"),
]

MINIMAL_ADMIN_COMMANDS = [
    *MINIMAL_USER_COMMANDS,
    BotCommand(command="admin", description="Відкрити адмін-меню"),
]

ADMIN_COMMANDS = [
    *USER_COMMANDS,
    BotCommand(command="admin", description="Відкрити адмін-меню"),
    BotCommand(command="users", description="Показати користувачів"),
    BotCommand(command="broadcast", description="Запустити розсилку"),
    BotCommand(command="ban", description="Заблокувати користувача"),
    BotCommand(command="unban", description="Розблокувати користувача"),
    BotCommand(command="premium", description="Видати Ліміт+ на строк"),
    BotCommand(command="premium_forever", description="Видати Ліміт+ назавжди"),
    BotCommand(command="unpremium", description="Зняти Ліміт+"),
    BotCommand(command="premium_status", description="Перевірити статус Ліміт+"),
]


def _format_command_setup_error(error: Exception) -> str:
    error_text = str(error).strip()
    if not error_text:
        return error.__class__.__name__

    return f"{error.__class__.__name__}: {error_text}"


def _should_retry_with_minimal_commands(error: Exception | None) -> bool:
    if not isinstance(error, TelegramBadRequest):
        return False

    return "command" in str(error).lower()


async def _try_set_bot_commands(
    bot: Bot,
    commands: list[BotCommand],
    scope: BotCommandScopeDefault | BotCommandScopeChat,
    log_label: str,
    language_code: str | None = None,
) -> Exception | None:
    try:
        await bot.set_my_commands(
            commands,
            scope=scope,
            language_code=language_code,
            request_timeout=COMMAND_SETUP_TIMEOUT_SECONDS,
        )
    except TelegramAPIError as error:
        logger.warning(
            "Не вдалося встановити %s: %s",
            log_label,
            _format_command_setup_error(error),
        )
        return error
    except Exception as error:
        logger.warning(
            "Не вдалося встановити %s: %s",
            log_label,
            _format_command_setup_error(error),
            exc_info=True,
        )
        return error

    logger.info("%s встановлено.", log_label)
    return None


async def _set_commands_for_scope(
    bot: Bot,
    commands: list[BotCommand],
    scope: BotCommandScopeDefault | BotCommandScopeChat,
    log_label: str,
) -> Exception | None:
    first_error = None

    for language_code in _command_language_codes_to_clear():
        error = await _try_set_bot_commands(
            bot,
            commands,
            scope,
            _command_log_label(log_label, language_code),
            language_code=language_code,
        )

        first_error = first_error or error

    return first_error


async def _try_delete_bot_commands(
    bot: Bot,
    scope: Any,
    log_label: str,
    language_code: str | None = None,
) -> Exception | None:
    try:
        await bot.delete_my_commands(
            scope=scope,
            language_code=language_code,
            request_timeout=COMMAND_SETUP_TIMEOUT_SECONDS,
        )
    except TelegramAPIError as error:
        logger.warning(
            "Не вдалося очистити %s: %s",
            log_label,
            _format_command_setup_error(error),
        )
        return error
    except Exception as error:
        logger.warning(
            "Не вдалося очистити %s: %s",
            log_label,
            _format_command_setup_error(error),
            exc_info=True,
        )
        return error

    logger.info("%s очищено.", log_label)
    return None


def _command_language_codes_to_clear() -> list[str | None]:
    return [None, *COMMAND_LANGUAGE_CODES_TO_CLEAR]


def _command_log_label(log_label: str, language_code: str | None) -> str:
    if language_code is None:
        return log_label

    return f"{log_label} language={language_code}"


async def _clear_commands_for_scope(
    bot: Bot,
    scope: Any,
    log_label: str,
) -> None:
    for language_code in _command_language_codes_to_clear():
        await _try_delete_bot_commands(
            bot,
            scope,
            _command_log_label(log_label, language_code),
            language_code=language_code,
        )


async def _clear_known_regular_user_commands(bot: Bot) -> None:
    try:
        user_ids = await get_all_users()
    except Exception as error:
        logger.warning(
            "Не вдалося прочитати користувачів для очищення chat-scoped команд: %s",
            _format_command_setup_error(error),
            exc_info=True,
        )
        return

    regular_user_ids = [
        user_id for user_id in user_ids
        if user_id not in ADMIN_IDS
    ]

    for user_id in regular_user_ids:
        await _clear_commands_for_scope(
            bot,
            BotCommandScopeChat(chat_id=user_id),
            f"chat-команди бота для user_id={user_id}",
        )

    if regular_user_ids:
        logger.info(
            "Очищено chat-scoped команди для %s звичайних користувачів.",
            len(regular_user_ids),
        )


async def setup_bot_commands(bot: Bot) -> None:
    user_error = None

    if HIDE_USER_COMMANDS:
        user_error = await _set_commands_for_scope(
            bot,
            MINIMAL_USER_COMMANDS,
            BotCommandScopeDefault(),
            "мінімальні команди бота для користувачів",
        )

        command_scopes_to_clear = [
            ("команди бота в приватних чатах", BotCommandScopeAllPrivateChats()),
            ("команди бота в групах", BotCommandScopeAllGroupChats()),
            (
                "команди бота для адміністраторів чатів",
                BotCommandScopeAllChatAdministrators(),
            ),
        ]

        for log_label, scope in command_scopes_to_clear:
            await _clear_commands_for_scope(
                bot,
                scope,
                log_label,
            )

        if CLEAR_KNOWN_USER_COMMANDS_ON_STARTUP:
            await _clear_known_regular_user_commands(bot)
    else:
        user_error = await _try_set_bot_commands(
            bot,
            USER_COMMANDS,
            BotCommandScopeDefault(),
            "команди бота для користувачів",
        )

    if not HIDE_USER_COMMANDS and _should_retry_with_minimal_commands(user_error):
        logger.warning(
            "Telegram відхилив повний список користувацьких команд. "
            "Пробую мінімальний набір."
        )
        await _try_set_bot_commands(
            bot,
            MINIMAL_USER_COMMANDS,
            BotCommandScopeDefault(),
            "мінімальні команди бота для користувачів",
        )

    for admin_id in ADMIN_IDS:
        admin_scope = BotCommandScopeChat(chat_id=admin_id)
        admin_error = await _try_set_bot_commands(
            bot,
            ADMIN_COMMANDS,
            admin_scope,
            f"адмін-команди бота для admin_id={admin_id}",
        )

        if _should_retry_with_minimal_commands(admin_error):
            logger.warning(
                "Telegram відхилив повний список адмін-команд для admin_id=%s. "
                "Пробую мінімальний набір.",
                admin_id,
            )
            await _try_set_bot_commands(
                bot,
                MINIMAL_ADMIN_COMMANDS,
                admin_scope,
                f"мінімальні адмін-команди бота для admin_id={admin_id}",
            )


# ============================================================
# MAIN
# ============================================================

def create_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    setup_middlewares(dp)
    include_project_routers(dp)

    return bot, dp


async def _start_api_server(bot: Bot, dp: Dispatcher):
    import uvicorn

    from services.api_app import create_app

    app = create_app(bot=bot, dispatcher=dp)
    config = uvicorn.Config(
        app,
        host=API_HOST,
        port=API_PORT,
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())

    logger.info("API server started on %s:%s", API_HOST, API_PORT)

    return server, task


async def _stop_api_server(server, task: asyncio.Task | None) -> None:
    if server is None or task is None:
        return

    server.should_exit = True

    with suppress(asyncio.CancelledError):
        await task


async def _setup_webhook(bot: Bot, dp: Dispatcher) -> None:
    if not TELEGRAM_WEBHOOK_SECRET_TOKEN:
        raise RuntimeError(
            "BOT_RUNTIME_MODE=webhook requires TELEGRAM_WEBHOOK_SECRET_TOKEN. "
            "Set it in the environment before exposing the webhook endpoint."
        )

    if not TELEGRAM_WEBHOOK_URL:
        logger.warning(
            "BOT_RUNTIME_MODE=webhook, but TELEGRAM_WEBHOOK_URL is empty. "
            "Webhook API will start without registering the URL in Telegram."
        )
        return

    await bot.set_webhook(
        TELEGRAM_WEBHOOK_URL,
        secret_token=TELEGRAM_WEBHOOK_SECRET_TOKEN or None,
        allowed_updates=dp.resolve_used_update_types(),
    )
    logger.info("Telegram webhook registered: %s", TELEGRAM_WEBHOOK_URL)


async def main() -> None:
    bot, dp = create_bot_and_dispatcher()

    cleanup_task: asyncio.Task | None = None
    maintenance_task: asyncio.Task | None = None
    api_server = None
    api_server_task: asyncio.Task | None = None

    await init_db()
    await setup_bot_commands(bot)

    if start_reading_audio_workers is not None:
        await start_reading_audio_workers()

    if cleanup_expired_reading_sessions is not None:
        cleanup_task = asyncio.create_task(
            reading_session_cleanup_worker()
        )
        logger.info("Фонове очищення reading-сесій запущено.")

    if run_maintenance_cleanup is not None:
        maintenance_task = asyncio.create_task(
            maintenance_cleanup_worker()
        )
        logger.info("Фонове maintenance cleanup запущено.")

    logger.info("Бот запущено.")

    try:
        if BOT_RUNTIME_MODE == "webhook":
            await _setup_webhook(bot, dp)
            api_server, api_server_task = await _start_api_server(bot, dp)
            await api_server_task
        else:
            if API_ENABLED:
                api_server, api_server_task = await _start_api_server(bot, dp)

            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
            )

    finally:
        await _stop_api_server(api_server, api_server_task)

        if cleanup_task is not None:
            cleanup_task.cancel()

            with suppress(asyncio.CancelledError):
                await cleanup_task

        if maintenance_task is not None:
            maintenance_task.cancel()

            with suppress(asyncio.CancelledError):
                await maintenance_task

        if close_reading_audio_queue is not None:
            await close_reading_audio_queue()

        if cleanup_all_reading_sessions is not None:
            await cleanup_all_reading_sessions()

        if close_http_session is not None:
            await close_http_session()

        if close_redis_client is not None:
            await close_redis_client()

        if close_telemetry_service is not None:
            await close_telemetry_service()

        await bot.session.close()
        logger.info("Бот зупинено.")


if __name__ == "__main__":
    asyncio.run(main())
