import pytest
from aiogram import Dispatcher


@pytest.mark.asyncio
async def test_smoke_import_router_setup_and_db_init(workspace_tmp_path, monkeypatch):
    from database import db as db_module

    db_path = workspace_tmp_path / "smoke.sqlite"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_path))

    await db_module.init_db()

    import bot

    dispatcher = Dispatcher()
    bot.setup_middlewares(dispatcher)
    bot.include_project_routers(dispatcher)

    assert db_path.exists()
    assert dispatcher.sub_routers
    assert bot.ROUTERS_ORDER[-1][0] == "handlers.messages"


def test_startup_dependency_loaders_map_optional_imports(monkeypatch):
    import bot

    requested_attrs = []

    class FakeMiddleware:
        pass

    async def fake_hook():
        return None

    def fake_import_optional_attr(module_path, attr_name, warning_message):
        requested_attrs.append((module_path, attr_name))

        if attr_name.endswith("Middleware"):
            return FakeMiddleware

        return fake_hook

    monkeypatch.setattr(bot, "_import_optional_attr", fake_import_optional_attr)

    middleware_factories = bot.load_middleware_factories()
    lifecycle_hooks = bot.load_lifecycle_hooks()

    assert middleware_factories.user_activity is FakeMiddleware
    assert middleware_factories.ban is FakeMiddleware
    assert middleware_factories.rate_limit is FakeMiddleware
    assert middleware_factories.redis_rate_limit is FakeMiddleware
    assert lifecycle_hooks.close_redis_client is fake_hook
    assert lifecycle_hooks.start_reading_audio_workers is fake_hook
    assert ("services.reading_service", "start_reading_audio_workers") in requested_attrs
    assert ("services.telemetry_service", "close_telemetry_service") in requested_attrs


def test_setup_middlewares_accepts_injected_factories(monkeypatch):
    import bot

    created_middlewares = []

    class FakeMiddleware:
        def __init__(self, *args, **kwargs):
            created_middlewares.append(kwargs)

        async def __call__(self, handler, event, data):
            return await handler(event, data)

    def fail_optional_import(*args, **kwargs):
        raise AssertionError("setup_middlewares should use injected factories")

    monkeypatch.setattr(bot, "_import_optional_attr", fail_optional_import)
    monkeypatch.setattr(bot, "RATE_LIMIT_BACKEND", "memory")

    dispatcher = Dispatcher()
    factories = bot.MiddlewareFactories(
        user_activity=FakeMiddleware,
        ban=FakeMiddleware,
        rate_limit=FakeMiddleware,
    )

    bot.setup_middlewares(dispatcher, middleware_factories=factories)

    assert len(created_middlewares) == 3
