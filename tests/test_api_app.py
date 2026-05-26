import asyncio

from aiogram import Bot
from fastapi.testclient import TestClient

from services import api_app
from services import runtime_state


def test_health_and_version_endpoints() -> None:
    runtime_state.reset_runtime_state()
    client = TestClient(api_app.create_app())

    health = client.get("/health")
    version = client.get("/version")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["runtime"]["status"] == "ok"
    assert version.status_code == 200
    assert version.json()["service"] == api_app.LOG_SERVICE_NAME


def test_health_reports_runtime_degradation() -> None:
    runtime_state.reset_runtime_state()
    runtime_state.record_runtime_error("worker", RuntimeError("boom"))

    client = TestClient(api_app.create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["runtime"]["status"] == "degraded"
    assert response.json()["runtime"]["components"][0]["component"] == "worker"

    runtime_state.reset_runtime_state()


def test_ready_returns_200_when_dependencies_are_ok(monkeypatch) -> None:
    async def ok_sqlite():
        return {"status": "ok"}

    async def ok_redis():
        return {"status": "skipped", "required": False}

    monkeypatch.setattr(api_app, "_check_sqlite", ok_sqlite)
    monkeypatch.setattr(api_app, "_check_redis", ok_redis)

    client = TestClient(api_app.create_app())
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_returns_503_when_dependency_fails(monkeypatch) -> None:
    async def ok_sqlite():
        return {"status": "ok"}

    async def fail_redis():
        raise RuntimeError("redis down")

    monkeypatch.setattr(api_app, "_check_sqlite", ok_sqlite)
    monkeypatch.setattr(api_app, "_check_redis", fail_redis)

    client = TestClient(api_app.create_app())
    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["redis"]["status"] == "error"


def test_metrics_endpoint_uses_optional_bearer_auth(monkeypatch) -> None:
    async def fake_get_service_metrics_summary(days: int):
        return {
            "days": days,
            "total_requests": 1,
            "total_errors": 0,
            "groups": [],
        }

    monkeypatch.setattr(api_app, "API_AUTH_TOKEN", "secret")
    monkeypatch.setattr(
        api_app,
        "get_service_metrics_summary",
        fake_get_service_metrics_summary,
    )

    client = TestClient(api_app.create_app())

    assert client.get("/metrics").status_code == 401

    response = client.get(
        "/metrics?days=7",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert response.json()["service_metrics"]["days"] == 7


def test_admin_stats_endpoint_returns_contract(monkeypatch) -> None:
    async def fake_get_admin_stats_snapshot(date: str):
        return {
            "date": date,
            "total_users": 2,
            "usage_totals": {},
        }

    monkeypatch.setattr(api_app, "API_AUTH_TOKEN", "")
    monkeypatch.setattr(
        api_app,
        "get_admin_stats_snapshot",
        fake_get_admin_stats_snapshot,
    )

    client = TestClient(api_app.create_app())
    response = client.get("/admin/stats?date=2026-05-19")

    assert response.status_code == 200
    assert response.json()["stats"]["date"] == "2026-05-19"


def test_webhook_requires_attached_runtime() -> None:
    client = TestClient(api_app.create_app())
    response = client.post("/webhook/telegram", json={"update_id": 1})

    assert response.status_code == 503


def test_webhook_mode_requires_secret(monkeypatch) -> None:
    monkeypatch.setattr(api_app, "BOT_RUNTIME_MODE", "webhook")
    monkeypatch.setattr(api_app, "TELEGRAM_WEBHOOK_SECRET_TOKEN", "")

    try:
        api_app.create_app()
    except RuntimeError as error:
        assert "TELEGRAM_WEBHOOK_SECRET_TOKEN" in str(error)
    else:
        raise AssertionError("webhook mode must fail fast without secret")


def test_webhook_rejects_invalid_secret(monkeypatch) -> None:
    monkeypatch.setattr(api_app, "TELEGRAM_WEBHOOK_SECRET_TOKEN", "secret")

    client = TestClient(api_app.create_app())
    response = client.post(
        "/webhook/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        json={"update_id": 1},
    )

    assert response.status_code == 401


def test_webhook_rejects_oversized_payload(monkeypatch) -> None:
    monkeypatch.setattr(api_app, "TELEGRAM_WEBHOOK_SECRET_TOKEN", "secret")
    monkeypatch.setattr(api_app, "MAX_WEBHOOK_BODY_BYTES", 8)

    client = TestClient(api_app.create_app())
    response = client.post(
        "/webhook/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        content=b'{"update_id":123}',
    )

    assert response.status_code == 413


def test_webhook_feeds_update_to_dispatcher() -> None:
    class FakeDispatcher:
        def __init__(self) -> None:
            self.updates = []

        async def feed_update(self, bot, update) -> None:
            self.updates.append((bot, update))

    bot = Bot(token="123456:test_bot_token")
    dispatcher = FakeDispatcher()

    try:
        client = TestClient(api_app.create_app(bot=bot, dispatcher=dispatcher))
        response = client.post("/webhook/telegram", json={"update_id": 123})

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert dispatcher.updates[0][0] is bot
        assert dispatcher.updates[0][1].update_id == 123

    finally:
        asyncio.run(bot.session.close())


def test_webhook_accepts_valid_secret(monkeypatch) -> None:
    class FakeDispatcher:
        def __init__(self) -> None:
            self.updates = []

        async def feed_update(self, bot, update) -> None:
            self.updates.append((bot, update))

    monkeypatch.setattr(api_app, "TELEGRAM_WEBHOOK_SECRET_TOKEN", "secret")

    bot = Bot(token="123456:test_bot_token")
    dispatcher = FakeDispatcher()

    try:
        client = TestClient(api_app.create_app(bot=bot, dispatcher=dispatcher))
        response = client.post(
            "/webhook/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
            json={"update_id": 456},
        )

        assert response.status_code == 200
        assert dispatcher.updates[0][1].update_id == 456

    finally:
        asyncio.run(bot.session.close())
