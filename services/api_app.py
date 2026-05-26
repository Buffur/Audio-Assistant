import hmac
import json
import time
from typing import Any

from aiogram import Bot, Dispatcher, types
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from config import (
    API_AUTH_TOKEN,
    APP_VERSION,
    BOT_RUNTIME_MODE,
    LOG_SERVICE_NAME,
    METRICS_REDIS_STREAM_ENABLED,
    READING_AUDIO_QUEUE_BACKEND,
    READING_AUDIO_QUEUE_REDIS_KEY,
    READING_SESSION_BACKEND,
    TELEGRAM_WEBHOOK_PATH,
    TELEGRAM_WEBHOOK_SECRET_TOKEN,
)
from database.db import get_admin_stats_snapshot, get_db_connection
from database.db import get_service_metrics_summary
from services.redis_client import get_redis_client
from services.runtime_state import get_runtime_health


STARTED_AT = time.time()
MAX_WEBHOOK_BODY_BYTES = 1024 * 1024


def _now() -> float:
    return time.time()


async def _require_api_auth(
    authorization: str | None = Header(default=None),
) -> None:
    if not API_AUTH_TOKEN:
        return

    expected = f"Bearer {API_AUTH_TOKEN}"

    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
        )


def validate_webhook_security() -> None:
    if BOT_RUNTIME_MODE == "webhook" and not TELEGRAM_WEBHOOK_SECRET_TOKEN:
        raise RuntimeError(
            "TELEGRAM_WEBHOOK_SECRET_TOKEN is required when "
            "BOT_RUNTIME_MODE=webhook."
        )


def _is_valid_webhook_secret(received_secret: str | None) -> bool:
    if not TELEGRAM_WEBHOOK_SECRET_TOKEN:
        return BOT_RUNTIME_MODE != "webhook"

    return hmac.compare_digest(
        received_secret or "",
        TELEGRAM_WEBHOOK_SECRET_TOKEN,
    )


def _ensure_webhook_body_size_allowed(content_length: int | None) -> None:
    if content_length is None:
        return

    if content_length > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Webhook payload is too large",
        )


async def _check_sqlite() -> dict[str, Any]:
    async with get_db_connection() as db:
        await db.execute("SELECT 1")

    return {
        "status": "ok",
    }


def _redis_is_required() -> bool:
    return (
        READING_SESSION_BACKEND == "redis"
        or READING_AUDIO_QUEUE_BACKEND == "redis"
        or METRICS_REDIS_STREAM_ENABLED
    )


async def _check_redis() -> dict[str, Any]:
    if not _redis_is_required():
        return {
            "status": "skipped",
            "required": False,
        }

    client = await get_redis_client()
    await client.ping()

    queue_size = None

    if READING_AUDIO_QUEUE_BACKEND == "redis":
        queue_size = int(await client.llen(READING_AUDIO_QUEUE_REDIS_KEY))

    return {
        "status": "ok",
        "required": True,
        "audio_queue_size": queue_size,
    }


async def _readiness_payload() -> tuple[int, dict[str, Any]]:
    checks: dict[str, Any] = {}
    ready = True

    try:
        checks["sqlite"] = await _check_sqlite()
    except Exception as error:
        ready = False
        checks["sqlite"] = {
            "status": "error",
            "error": error.__class__.__name__,
        }

    try:
        checks["redis"] = await _check_redis()
    except RedisError as error:
        ready = False
        checks["redis"] = {
            "status": "error",
            "required": _redis_is_required(),
            "error": error.__class__.__name__,
        }
    except Exception as error:
        ready = False
        checks["redis"] = {
            "status": "error",
            "required": _redis_is_required(),
            "error": error.__class__.__name__,
        }

    checks["runtime"] = get_runtime_health()

    payload = {
        "status": "ready" if ready else "not_ready",
        "service": LOG_SERVICE_NAME,
        "version": APP_VERSION,
        "mode": BOT_RUNTIME_MODE,
        "checks": checks,
    }

    return status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE, payload


def _get_runtime(request: Request) -> tuple[Bot | None, Dispatcher | None]:
    bot = getattr(request.app.state, "bot", None)
    dispatcher = getattr(request.app.state, "dispatcher", None)

    return bot, dispatcher


def create_app(
    *,
    bot: Bot | None = None,
    dispatcher: Dispatcher | None = None,
) -> FastAPI:
    validate_webhook_security()

    app = FastAPI(
        title="Audio Assistant API",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
    )
    app.state.bot = bot
    app.state.dispatcher = dispatcher

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": LOG_SERVICE_NAME,
            "version": APP_VERSION,
            "mode": BOT_RUNTIME_MODE,
            "uptime_seconds": round(_now() - STARTED_AT, 3),
            "runtime": get_runtime_health(),
        }

    @app.get("/version")
    async def version() -> dict[str, Any]:
        return {
            "service": LOG_SERVICE_NAME,
            "version": APP_VERSION,
            "mode": BOT_RUNTIME_MODE,
        }

    @app.get("/ready")
    async def ready() -> JSONResponse:
        status_code, payload = await _readiness_payload()
        return JSONResponse(status_code=status_code, content=payload)

    @app.get("/metrics", dependencies=[Depends(_require_api_auth)])
    async def metrics(days: int = 1) -> dict[str, Any]:
        if days <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="days must be greater than 0",
            )

        return {
            "service": LOG_SERVICE_NAME,
            "version": APP_VERSION,
            "service_metrics": await get_service_metrics_summary(days=days),
        }

    @app.get("/admin/stats", dependencies=[Depends(_require_api_auth)])
    async def admin_stats(date: str) -> dict[str, Any]:
        return {
            "service": LOG_SERVICE_NAME,
            "version": APP_VERSION,
            "stats": await get_admin_stats_snapshot(date),
        }

    @app.post(TELEGRAM_WEBHOOK_PATH)
    async def telegram_webhook(
        request: Request,
        content_length: int | None = Header(default=None),
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        _ensure_webhook_body_size_allowed(content_length)

        if not _is_valid_webhook_secret(x_telegram_bot_api_secret_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Telegram webhook secret",
            )

        bot_instance, dispatcher = _get_runtime(request)

        if bot_instance is None or dispatcher is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Telegram runtime is not attached",
            )

        raw_body = await request.body()

        if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Webhook payload is too large",
            )

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload",
            ) from None

        update = types.Update.model_validate(payload, context={"bot": bot_instance})
        await dispatcher.feed_update(bot_instance, update)

        return {
            "ok": True,
        }

    return app
