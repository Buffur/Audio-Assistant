import pytest

from database import db as db_module


@pytest.mark.asyncio
async def test_user_settings_and_ban_flow(workspace_tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "DB_PATH", str(workspace_tmp_path / "bot.sqlite"))

    await db_module.init_db()
    await db_module.register_or_update_user(
        user_id=1,
        username="@tester",
        full_name="Test User",
    )

    assert await db_module.get_user_settings(1) == (None, None)

    await db_module.set_user_settings(1, voice="uk-UA-OstapNeural")
    assert await db_module.get_user_settings(1) == ("uk-UA-OstapNeural", None)

    assert await db_module.get_user_tts_provider(1) is None
    await db_module.set_user_tts_provider(1, "piper")
    assert await db_module.get_user_tts_provider(1) == "piper"

    assert await db_module.is_user_banned(1) is False
    await db_module.ban_user(1)
    assert await db_module.is_user_banned(1) is True
    await db_module.unban_user(1)
    assert await db_module.is_user_banned(1) is False


@pytest.mark.asyncio
async def test_usage_increment_under_limit_is_atomic(workspace_tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "DB_PATH", str(workspace_tmp_path / "usage.sqlite"))

    await db_module.init_db()

    assert await db_module.try_increment_daily_usage_under_limit(
        user_id=1,
        usage_date="2026-05-13",
        field_name="text_messages_processed",
        limit=2,
    ) is True
    assert await db_module.try_increment_daily_usage_under_limit(
        user_id=1,
        usage_date="2026-05-13",
        field_name="text_messages_processed",
        limit=2,
    ) is True
    assert await db_module.try_increment_daily_usage_under_limit(
        user_id=1,
        usage_date="2026-05-13",
        field_name="text_messages_processed",
        limit=2,
    ) is False

    usage = await db_module.get_daily_usage(1, "2026-05-13")
    assert usage["text_messages_processed"] == 2


@pytest.mark.asyncio
async def test_document_history_crud(workspace_tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "DB_PATH", str(workspace_tmp_path / "history.sqlite"))

    await db_module.init_db()

    document_id = await db_module.add_document_history(
        user_id=1,
        source_type="text",
        source_name="Text message",
        text_preview="Preview",
        text_length=100,
        chunks_count=2,
        chunks_json='["one", "two"]',
    )

    history = await db_module.get_user_document_history(1)
    assert len(history) == 1
    assert history[0]["id"] == document_id
    assert history[0]["has_chunks"] is True

    document = await db_module.get_user_document_by_id(1, document_id)
    assert document is not None
    assert document["chunks_json"] == '["one", "two"]'

    await db_module.delete_user_document(1, document_id)
    assert await db_module.get_user_document_by_id(1, document_id) is None


@pytest.mark.asyncio
async def test_document_history_pagination_and_count(workspace_tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "DB_PATH", str(workspace_tmp_path / "history_pages.sqlite"))

    await db_module.init_db()

    for index in range(3):
        await db_module.add_document_history(
            user_id=1,
            source_type="text",
            source_name=f"Text message {index}",
            text_preview=f"Preview {index}",
            text_length=100,
            chunks_count=1,
            chunks_json='["one"]',
        )

    assert await db_module.count_user_document_history(1) == 3

    first_page = await db_module.get_user_document_history(1, limit=2, offset=0)
    second_page = await db_module.get_user_document_history(1, limit=2, offset=2)

    assert len(first_page) == 2
    assert len(second_page) == 1


@pytest.mark.asyncio
async def test_rejects_invalid_usage_field(workspace_tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "DB_PATH", str(workspace_tmp_path / "invalid.sqlite"))

    await db_module.init_db()

    with pytest.raises(ValueError):
        await db_module.increment_daily_usage(
            user_id=1,
            usage_date="2026-05-13",
            field_name="unknown",
        )


@pytest.mark.asyncio
async def test_app_settings_roundtrip(workspace_tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "DB_PATH", str(workspace_tmp_path / "settings.sqlite"))

    await db_module.init_db()

    assert await db_module.get_app_setting("limit.text_messages") is None

    await db_module.set_app_setting("limit.text_messages", "50")

    assert await db_module.get_app_setting("limit.text_messages") == "50"
    assert await db_module.get_app_settings(["limit.text_messages"]) == {
        "limit.text_messages": "50",
    }
