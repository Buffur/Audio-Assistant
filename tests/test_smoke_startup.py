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
