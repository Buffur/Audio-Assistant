import pytest
import pytest_asyncio

from keyboards.reading import READ_SUMMARY_ACTION
from services import reading_service
from services import reading_session_store as store


class FakeStatusMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.edits: list[str] = []
        self.deleted = False
        self.message_id = 42

    async def edit_text(self, text: str) -> None:
        self.edits.append(text)
        self.text = text

    async def delete(self) -> None:
        self.deleted = True


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.answer_kwargs: list[dict] = []
        self.status_messages: list[FakeStatusMessage] = []
        self.chat = type("FakeChat", (), {"id": 1001})()

    async def answer(self, text: str, **kwargs):
        self.answers.append(text)
        self.answer_kwargs.append(kwargs)
        status = FakeStatusMessage(text)
        self.status_messages.append(status)
        return status


@pytest_asyncio.fixture(autouse=True)
async def cleanup_reading_state():
    await reading_service.close_reading_audio_queue(timeout_seconds=0.1)
    await store.cleanup_all_reading_sessions()
    reading_service._privacy_delete_markers.clear()
    yield
    await reading_service.close_reading_audio_queue(timeout_seconds=0.1)
    await store.cleanup_all_reading_sessions()
    reading_service._privacy_delete_markers.clear()


@pytest.mark.asyncio
async def test_send_audio_chunk_enqueues_background_job(monkeypatch) -> None:
    captured = {}

    async def fake_send_audio_chunk_now(
        message,
        user_id,
        expected_session_id,
        status_msg,
        job_created_at=None,
    ) -> None:
        captured.update(
            {
                "message": message,
                "user_id": user_id,
                "expected_session_id": expected_session_id,
                "status_msg": status_msg,
                "job_created_at": job_created_at,
            }
        )

    monkeypatch.setattr(
        reading_service,
        "_send_audio_chunk_now",
        fake_send_audio_chunk_now,
    )

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["one"],
            "index": 0,
        },
    )

    message = FakeMessage()

    await reading_service.send_audio_chunk(message, user_id=1)
    await reading_service.close_reading_audio_queue(timeout_seconds=1.0)

    assert captured["message"] is message
    assert captured["user_id"] == 1
    assert captured["expected_session_id"] == "session-1"
    assert captured["status_msg"] in message.status_messages
    assert isinstance(captured["job_created_at"], float)
    assert message.answers


@pytest.mark.asyncio
async def test_send_audio_chunk_can_enqueue_serialized_redis_job(monkeypatch) -> None:
    captured = {}

    async def fake_queue_position() -> int:
        return 7

    async def fake_enqueue(job) -> None:
        captured.update(job)

    monkeypatch.setattr(reading_service, "READING_AUDIO_QUEUE_BACKEND", "redis")
    monkeypatch.setattr(
        reading_service,
        "_redis_audio_queue_position",
        fake_queue_position,
    )
    monkeypatch.setattr(
        reading_service,
        "_enqueue_redis_audio_job",
        fake_enqueue,
    )

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-redis",
            "chunks": ["one"],
            "index": 0,
        },
    )

    message = FakeMessage()

    await reading_service.send_audio_chunk(message, user_id=1)

    assert captured.pop("created_at") > 0
    assert captured == {
        "type": "send_chunk",
        "user_id": 1,
        "chat_id": 1001,
        "session_id": "session-redis",
        "status_message_id": 42,
    }
    assert "Почну, щойно звільниться обробка." in message.answers[0]


@pytest.mark.asyncio
async def test_send_audio_chunk_reports_full_redis_queue_without_memory_fallback(
    monkeypatch,
) -> None:
    async def fake_queue_position() -> int:
        return 20

    async def fake_enqueue(job) -> None:
        raise reading_service.asyncio.QueueFull

    def fail_memory_queue():
        raise AssertionError("full Redis queue must not fall back to memory queue")

    monkeypatch.setattr(reading_service, "READING_AUDIO_QUEUE_BACKEND", "redis")
    monkeypatch.setattr(
        reading_service,
        "_redis_audio_queue_position",
        fake_queue_position,
    )
    monkeypatch.setattr(
        reading_service,
        "_enqueue_redis_audio_job",
        fake_enqueue,
    )
    monkeypatch.setattr(
        reading_service,
        "_ensure_audio_generation_queue",
        fail_memory_queue,
    )

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-full",
            "chunks": ["one"],
            "index": 0,
        },
    )

    message = FakeMessage()

    await reading_service.send_audio_chunk(message, user_id=1)

    assert reading_service.AUDIO_QUEUE_FULL_TEXT in message.answers
    assert message.status_messages[0].deleted is True


@pytest.mark.asyncio
async def test_export_reading_audio_enqueues_background_job(monkeypatch) -> None:
    captured = {}

    async def fake_export_reading_audio_now(
        message,
        user_id,
        expected_session_id,
        status_msg,
        job_created_at=None,
    ) -> None:
        captured.update(
            {
                "message": message,
                "user_id": user_id,
                "expected_session_id": expected_session_id,
                "status_msg": status_msg,
                "job_created_at": job_created_at,
            }
        )

    monkeypatch.setattr(
        reading_service,
        "_export_reading_audio_now",
        fake_export_reading_audio_now,
    )

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["one", "two"],
            "index": 1,
        },
    )

    message = FakeMessage()

    await reading_service.export_reading_audio(message, user_id=1)
    await reading_service.close_reading_audio_queue(timeout_seconds=1.0)

    assert captured["message"] is message
    assert captured["user_id"] == 1
    assert captured["expected_session_id"] == "session-1"
    assert captured["status_msg"] in message.status_messages
    assert isinstance(captured["job_created_at"], float)
    assert message.answers


@pytest.mark.asyncio
async def test_send_audio_chunk_hides_summary_after_summary_generated(
    monkeypatch,
) -> None:
    captured = {}

    async def fake_get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+0%"

    async def fake_get_effective_user_tts_provider(user_id: int) -> str:
        return "edge"

    async def fake_is_premium_user(user_id: int) -> bool:
        return False

    async def fake_get_audio_from_prefetch_or_generate(**kwargs):
        captured["current_part"] = kwargs["current_part"]
        captured["total_parts"] = kwargs["total_parts"]
        return ["chunk.ogg"]

    async def fake_send_audio_files(**kwargs) -> None:
        captured["reply_markup"] = kwargs["reply_markup"]
        captured["caption"] = kwargs["caption"]
        captured["audio_files"] = kwargs["audio_files"]

    monkeypatch.setattr(
        reading_service,
        "get_effective_user_settings",
        fake_get_effective_user_settings,
    )
    monkeypatch.setattr(
        reading_service,
        "get_effective_user_tts_provider",
        fake_get_effective_user_tts_provider,
    )
    monkeypatch.setattr(reading_service, "is_premium_user", fake_is_premium_user)
    monkeypatch.setattr(
        reading_service,
        "_get_audio_from_prefetch_or_generate",
        fake_get_audio_from_prefetch_or_generate,
    )
    monkeypatch.setattr(reading_service, "_send_audio_files", fake_send_audio_files)

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-summary",
            "chunks": ["one"],
            "index": 0,
            "is_generating": True,
            "summary_text": "already generated",
            "summary_delivered": True,
        },
    )

    message = FakeMessage()

    await reading_service._send_audio_chunk_now(
        message=message,
        user_id=1,
        expected_session_id="session-summary",
        status_msg=None,
    )

    callbacks = [
        button.callback_data
        for row in message.answer_kwargs[-1]["reply_markup"].inline_keyboard
        for button in row
    ]
    session = await store.get_reading_session(1)

    assert captured["current_part"] == 1
    assert captured["total_parts"] == 1
    assert captured["audio_files"] == ["chunk.ogg"]
    assert captured["reply_markup"] is None
    assert all(not callback.startswith(READ_SUMMARY_ACTION) for callback in callbacks)
    assert message.answers == [reading_service.ALL_PARTS_SENT_AFTER_SUMMARY_TEXT]
    assert session["index"] == 1
    assert session["is_generating"] is False


@pytest.mark.asyncio
async def test_send_audio_chunk_keeps_summary_button_for_cached_catalog_summary(
    monkeypatch,
) -> None:
    captured = {}

    async def fake_get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+0%"

    async def fake_get_effective_user_tts_provider(user_id: int) -> str:
        return "edge"

    async def fake_is_premium_user(user_id: int) -> bool:
        return False

    async def fake_get_audio_from_prefetch_or_generate(**kwargs):
        return ["chunk.ogg"]

    async def fake_send_audio_files(**kwargs) -> None:
        captured["reply_markup"] = kwargs["reply_markup"]

    monkeypatch.setattr(
        reading_service,
        "get_effective_user_settings",
        fake_get_effective_user_settings,
    )
    monkeypatch.setattr(
        reading_service,
        "get_effective_user_tts_provider",
        fake_get_effective_user_tts_provider,
    )
    monkeypatch.setattr(reading_service, "is_premium_user", fake_is_premium_user)
    monkeypatch.setattr(
        reading_service,
        "_get_audio_from_prefetch_or_generate",
        fake_get_audio_from_prefetch_or_generate,
    )
    monkeypatch.setattr(reading_service, "_send_audio_files", fake_send_audio_files)

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "catalog-session",
            "chunks": ["one"],
            "index": 0,
            "is_generating": True,
            "summary_text": "cached summary from catalog",
            "summary_delivered": False,
        },
    )

    message = FakeMessage()

    await reading_service._send_audio_chunk_now(
        message=message,
        user_id=1,
        expected_session_id="catalog-session",
        status_msg=None,
    )

    callbacks = [
        button.callback_data
        for row in message.answer_kwargs[-1]["reply_markup"].inline_keyboard
        for button in row
    ]

    assert captured["reply_markup"] is None
    assert any(callback.startswith(READ_SUMMARY_ACTION) for callback in callbacks)
    assert message.answers == [reading_service.ALL_PARTS_SENT_TEXT]


@pytest.mark.asyncio
async def test_privacy_delete_marker_skips_jobs_created_before_deletion() -> None:
    user_id = 77

    await reading_service.mark_user_data_deletion(user_id)

    deleted_at = await reading_service._get_user_data_deletion_timestamp(user_id)

    assert deleted_at is not None
    assert await reading_service._should_skip_deleted_user_job(
        user_id,
        deleted_at - 0.01,
    )
    assert not await reading_service._should_skip_deleted_user_job(
        user_id,
        deleted_at + 0.01,
    )


@pytest.mark.asyncio
async def test_cleanup_user_private_runtime_data_clears_session_queue_and_cache(
    monkeypatch,
) -> None:
    async def fake_purge_queued_audio_jobs_for_user(user_id: int) -> int:
        assert user_id == 88
        return 2

    def fake_clear_audio_cache() -> dict[str, int]:
        return {"removed_files": 3, "removed_bytes": 4096}

    monkeypatch.setattr(
        reading_service,
        "purge_queued_audio_jobs_for_user",
        fake_purge_queued_audio_jobs_for_user,
    )
    monkeypatch.setattr(reading_service, "clear_audio_cache", fake_clear_audio_cache)

    await store.set_reading_session(
        user_id=88,
        session={
            "session_id": "private-session",
            "chunks": ["one"],
            "index": 0,
        },
    )

    result = await reading_service.cleanup_user_private_runtime_data(88)

    assert result == {
        "reading_session": 1,
        "queued_audio_jobs": 2,
        "audio_cache_files": 3,
    }
    assert await store.get_reading_session(88) is None
