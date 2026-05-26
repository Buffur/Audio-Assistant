from types import SimpleNamespace

import pytest

from middlewares import ban as ban_middleware_module
from middlewares import rate_limit as rate_limit_module
from middlewares import redis_rate_limit as redis_rate_limit_module
from middlewares import user_activity as user_activity_module


async def _ok_handler(event, data):
    _ok_handler.calls += 1
    return "ok"


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_limit(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module, "ADMIN_IDS", [])
    _ok_handler.calls = 0

    middleware = rate_limit_module.RateLimitMiddleware(
        max_events=1,
        period_seconds=10,
        warning_cooldown_seconds=10,
    )
    event = SimpleNamespace(from_user=SimpleNamespace(id=10))

    assert await middleware(_ok_handler, event, {}) == "ok"
    assert await middleware(_ok_handler, event, {}) is None
    assert _ok_handler.calls == 1


@pytest.mark.asyncio
async def test_rate_limit_skips_admin(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module, "ADMIN_IDS", [10])
    _ok_handler.calls = 0

    middleware = rate_limit_module.RateLimitMiddleware(max_events=1)
    event = SimpleNamespace(from_user=SimpleNamespace(id=10))

    assert await middleware(_ok_handler, event, {}) == "ok"
    assert await middleware(_ok_handler, event, {}) == "ok"
    assert _ok_handler.calls == 2


@pytest.mark.asyncio
async def test_redis_rate_limit_uses_memory_fallback_on_redis_error(monkeypatch) -> None:
    async def fake_is_allowed(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(redis_rate_limit_module, "ADMIN_IDS", [])
    _ok_handler.calls = 0

    middleware = redis_rate_limit_module.RedisRateLimitMiddleware(
        max_events=1,
        period_seconds=10,
        warning_cooldown_seconds=10,
    )
    monkeypatch.setattr(middleware, "_is_allowed", fake_is_allowed)
    event = SimpleNamespace(from_user=SimpleNamespace(id=10))

    assert await middleware(_ok_handler, event, {}) == "ok"
    assert await middleware(_ok_handler, event, {}) is None
    assert _ok_handler.calls == 1


@pytest.mark.asyncio
async def test_ban_middleware_blocks_banned_user(monkeypatch) -> None:
    async def fake_is_user_banned(user_id):
        return True

    monkeypatch.setattr(ban_middleware_module, "ADMIN_IDS", [])
    monkeypatch.setattr(ban_middleware_module, "is_user_banned", fake_is_user_banned)
    _ok_handler.calls = 0

    middleware = ban_middleware_module.BanMiddleware()
    event = SimpleNamespace(from_user=SimpleNamespace(id=10))

    assert await middleware(_ok_handler, event, {}) is None
    assert _ok_handler.calls == 0


@pytest.mark.asyncio
async def test_user_activity_registers_user(monkeypatch) -> None:
    captured = {}

    async def fake_register_or_update_user(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        user_activity_module,
        "register_or_update_user",
        fake_register_or_update_user,
    )
    _ok_handler.calls = 0

    middleware = user_activity_module.UserActivityMiddleware()
    event = SimpleNamespace(
        from_user=SimpleNamespace(
            id=10,
            username="tester",
            full_name="Test User",
        )
    )

    assert await middleware(_ok_handler, event, {}) == "ok"
    assert captured == {
        "user_id": 10,
        "username": "@tester",
        "full_name": "Test User",
    }
    assert _ok_handler.calls == 1


@pytest.mark.asyncio
async def test_user_activity_throttles_repeated_updates(monkeypatch) -> None:
    calls = []
    now = 100.0

    async def fake_register_or_update_user(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        user_activity_module,
        "register_or_update_user",
        fake_register_or_update_user,
    )
    _ok_handler.calls = 0

    middleware = user_activity_module.UserActivityMiddleware(
        update_interval_seconds=60,
        monotonic=lambda: now,
    )
    event = SimpleNamespace(
        from_user=SimpleNamespace(
            id=10,
            username="tester",
            full_name="Test User",
        )
    )

    assert await middleware(_ok_handler, event, {}) == "ok"
    assert await middleware(_ok_handler, event, {}) == "ok"

    assert len(calls) == 1
    assert _ok_handler.calls == 2


@pytest.mark.asyncio
async def test_user_activity_updates_immediately_on_profile_change(monkeypatch) -> None:
    calls = []
    now = 100.0

    async def fake_register_or_update_user(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        user_activity_module,
        "register_or_update_user",
        fake_register_or_update_user,
    )

    middleware = user_activity_module.UserActivityMiddleware(
        update_interval_seconds=60,
        monotonic=lambda: now,
    )
    event = SimpleNamespace(
        from_user=SimpleNamespace(
            id=10,
            username="tester",
            full_name="Test User",
        )
    )

    await middleware(_ok_handler, event, {})
    event.from_user.full_name = "Renamed User"
    await middleware(_ok_handler, event, {})

    assert [call["full_name"] for call in calls] == [
        "Test User",
        "Renamed User",
    ]
