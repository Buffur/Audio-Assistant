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
async def test_admin_stats_snapshot_uses_aggregated_usage(workspace_tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "DB_PATH", str(workspace_tmp_path / "admin.sqlite"))

    await db_module.init_db()
    await db_module.register_or_update_user(1, "@one", "One")
    await db_module.register_or_update_user(2, "@two", "Two")
    await db_module.register_or_update_user(3, "@three", "Three")
    await db_module.ban_user(2)
    await db_module.set_user_premium(3, premium_until=None)

    await db_module.increment_daily_usage(1, "2026-05-19", "text_messages_processed", 2)
    await db_module.increment_daily_usage(2, "2026-05-19", "files_processed", 1)
    await db_module.increment_daily_usage(3, "2026-05-19", "summaries_generated", 4)
    await db_module.increment_daily_usage(3, "2026-05-18", "links_processed", 10)

    snapshot = await db_module.get_admin_stats_snapshot("2026-05-19")

    assert snapshot["total_users"] == 3
    assert snapshot["active_users"] == 2
    assert snapshot["banned_users"] == 1
    assert snapshot["premium_users"] == 1
    assert snapshot["free_users"] == 2
    assert snapshot["usage_totals"] == {
        "text_messages_processed": 2,
        "files_processed": 1,
        "ocr_processed": 0,
        "links_processed": 0,
        "summaries_generated": 4,
    }


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


@pytest.mark.asyncio
async def test_service_metrics_summary_and_cleanup(workspace_tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "DB_PATH", str(workspace_tmp_path / "metrics.sqlite"))

    await db_module.init_db()

    await db_module.add_service_metric(
        provider="gemini",
        operation="ocr",
        success=False,
        latency_ms=1200,
        input_units=300,
        estimated_cost_usd=0.01,
        error_type="RuntimeError",
        error_message="temporary failure",
    )
    await db_module.add_service_metric(
        provider="edge",
        operation="tts",
        success=True,
        latency_ms=250,
        input_units=120,
    )
    await db_module.add_service_metric(
        provider="gemini",
        operation="parser",
        success=True,
        latency_ms=100,
        created_at="2000-01-01 00:00:00",
    )

    summary = await db_module.get_service_metrics_summary(days=1)

    assert summary["total_requests"] == 2
    assert summary["total_errors"] == 1
    assert summary["max_latency_ms"] == 1200
    assert summary["estimated_cost_usd"] == 0.01
    assert summary["groups"][0]["provider"] == "gemini"
    assert summary["groups"][0]["operation"] == "ocr"
    assert summary["groups"][0]["errors"] == 1

    assert await db_module.cleanup_service_metrics_older_than(days=1) == 1


@pytest.mark.asyncio
async def test_retention_and_delete_user_private_data(workspace_tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db_module, "DB_PATH", str(workspace_tmp_path / "retention.sqlite"))

    await db_module.init_db()
    await db_module.register_or_update_user(1, "@tester", "Test User")
    await db_module.set_user_settings(1, voice="uk-UA-OstapNeural", rate="+25%")
    await db_module.set_user_tts_provider(1, "piper")
    await db_module.set_user_premium(1, None)
    await db_module.ban_user(1)
    await db_module.increment_daily_usage(
        user_id=1,
        usage_date="2026-05-15",
        field_name="text_messages_processed",
    )

    old_document_id = await db_module.add_document_history(
        user_id=1,
        source_type="text",
        source_name="Old",
        text_preview="Old",
        text_length=10,
        chunks_count=1,
        chunks_json='["old"]',
    )
    await db_module.add_document_history(
        user_id=1,
        source_type="text",
        source_name="New",
        text_preview="New",
        text_length=10,
        chunks_count=1,
        chunks_json='["new"]',
    )

    async with db_module.get_db_connection() as raw_db:
        await raw_db.execute(
            "UPDATE document_history SET created_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", old_document_id),
        )
        await raw_db.commit()

    assert await db_module.delete_document_history_older_than(days=1) == 1
    assert await db_module.count_user_document_history(1) == 1

    result = await db_module.delete_user_private_data(1)

    assert result == {
        "document_history": 1,
        "usage_daily": 1,
        "user_settings": 1,
    }
    assert await db_module.count_user_document_history(1) == 0
    assert await db_module.get_user_settings(1) == (None, None)
    assert await db_module.get_user_tts_provider(1) is None
    assert await db_module.is_user_banned(1) is True
    assert (await db_module.get_user_plan_info(1))["plan"] == "premium"
