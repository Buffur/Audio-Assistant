import asyncio
import json

import pytest
import pytest_asyncio
from redis.exceptions import RedisError

from keyboards.reading import READ_SUMMARY_ACTION
from services import reading_audio_queue
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


async def healthy_redis_queue_stats() -> reading_audio_queue.AudioQueueStats:
    return reading_audio_queue.AudioQueueStats(
        backend="redis",
        max_size=20,
        pending=0,
        processing=0,
        worker_running=True,
    )


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
async def test_start_reading_session_creates_session_and_replaces_old_one() -> None:
    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "old-session",
            "chunks": ["old"],
            "index": 0,
        },
    )

    session = await reading_service.start_reading_session(
        user_id=1,
        chunks=["one", "two"],
        catalog_document_id=42,
        summary_text=" Cached summary ",
        summary_voice_file_ids=["voice-file-id"],
        summary_voice_voice="uk-UA-PolinaNeural",
        summary_voice_rate="+0%",
        summary_voice_provider="edge",
    )

    stored_session = await store.get_reading_session(1)

    assert stored_session == session
    assert session["session_id"] != "old-session"
    assert session["chunks"] == ["one", "two"]
    assert session["index"] == 0
    assert session["is_generating"] is True
    assert session["catalog_document_id"] == 42
    assert session["summary_text"] == "Cached summary"
    assert session["summary_delivered"] is False
    assert session["summary_voice_file_ids"] == ["voice-file-id"]
    assert session["summary_voice_voice"] == "uk-UA-PolinaNeural"


@pytest.mark.asyncio
async def test_is_audio_generation_active_reflects_session_state() -> None:
    assert await reading_service.is_audio_generation_active(1) is False

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["one"],
            "index": 0,
            "is_generating": True,
        },
    )

    assert await reading_service.is_audio_generation_active(1) is True

    await store.update_reading_session(1, is_generating=False)

    assert await reading_service.is_audio_generation_active(1) is False


@pytest.mark.asyncio
async def test_reply_with_voice_sends_error_text_without_tts(monkeypatch) -> None:
    message = FakeMessage()
    status_msg = FakeStatusMessage("processing")

    async def fail_generate_voice(*args, **kwargs):
        raise AssertionError("error text must not use TTS")

    monkeypatch.setattr(reading_service, "generate_voice", fail_generate_voice)

    await reading_service.reply_with_voice(
        message=message,
        user_id=1,
        text=reading_service.CHUNK_AUDIO_GENERATION_ERROR,
        status_msg=status_msg,
    )

    assert message.answers == [reading_service.CHUNK_AUDIO_GENERATION_ERROR]
    assert status_msg.deleted is True


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

    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_BACKEND", "redis")
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
        "_get_audio_queue_stats",
        healthy_redis_queue_stats,
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
    assert "Позиція в черзі: 7." in message.answers[0]
    assert "Нічого натискати не потрібно" in message.answers[0]


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

    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_BACKEND", "redis")
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
        "_get_audio_queue_stats",
        healthy_redis_queue_stats,
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
async def test_send_audio_chunk_reports_redis_queue_failure_without_memory_fallback(
    monkeypatch,
) -> None:
    async def fake_queue_position() -> int:
        return 1

    async def fake_enqueue(job) -> None:
        raise RedisError("redis down")

    def fail_memory_queue():
        raise AssertionError("Redis outage must not fall back to memory queue")

    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_BACKEND", "redis")
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
        "_get_audio_queue_stats",
        healthy_redis_queue_stats,
    )
    monkeypatch.setattr(
        reading_service,
        "_ensure_audio_generation_queue",
        fail_memory_queue,
    )

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-redis-down",
            "chunks": ["one"],
            "index": 0,
        },
    )

    message = FakeMessage()

    await reading_service.send_audio_chunk(message, user_id=1)

    session = await store.get_reading_session(1)

    assert reading_service.BACKGROUND_GENERATION_ERROR in message.answers
    assert message.status_messages[0].deleted is True
    assert session["is_generating"] is False


@pytest.mark.asyncio
async def test_enqueue_redis_audio_job_uses_active_capacity_script(monkeypatch) -> None:
    captured = {}

    class FakeRedis:
        async def eval(
            self,
            script: str,
            keys_count: int,
            pending_key: str,
            processing_key: str,
            prefetch_pending_key: str,
            prefetch_processing_key: str,
            target_pending_key: str,
            max_size: str,
            value: str,
        ) -> int:
            captured["script"] = script
            captured["keys_count"] = keys_count
            captured["pending_key"] = pending_key
            captured["processing_key"] = processing_key
            captured["prefetch_pending_key"] = prefetch_pending_key
            captured["prefetch_processing_key"] = prefetch_processing_key
            captured["target_pending_key"] = target_pending_key
            captured["max_size"] = max_size
            captured["payload"] = value
            return 1

    async def fake_start_workers(job_handler) -> None:
        captured["started"] = True

    async def fake_get_redis_client():
        return FakeRedis()

    async def fake_job_handler(bot, job) -> None:
        return None

    monkeypatch.setattr(reading_audio_queue, "start_audio_workers", fake_start_workers)
    monkeypatch.setattr(reading_audio_queue, "get_redis_client", fake_get_redis_client)

    await reading_audio_queue.enqueue_redis_audio_job(
        reading_audio_queue.build_send_chunk_job(
            user_id=1,
            chat_id=1001,
            session_id="session-1",
            status_message_id=None,
        ),
        fake_job_handler,
    )

    assert captured["started"] is True
    assert captured["keys_count"] == 5
    assert captured["pending_key"] == reading_audio_queue.READING_AUDIO_QUEUE_REDIS_KEY
    assert captured["processing_key"] == reading_audio_queue.REDIS_AUDIO_QUEUE_PROCESSING_KEY
    assert (
        captured["prefetch_pending_key"]
        == reading_audio_queue.REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY
    )
    assert (
        captured["prefetch_processing_key"]
        == reading_audio_queue.REDIS_PREFETCH_AUDIO_QUEUE_PROCESSING_KEY
    )
    assert (
        captured["target_pending_key"]
        == reading_audio_queue.READING_AUDIO_QUEUE_REDIS_KEY
    )
    assert captured["max_size"] == str(reading_audio_queue.READING_AUDIO_QUEUE_MAX_SIZE)
    assert "pending + processing" in captured["script"]
    assert '"type":"send_chunk"' in captured["payload"]


@pytest.mark.asyncio
async def test_enqueue_redis_audio_job_rejects_when_active_capacity_is_full(
    monkeypatch,
) -> None:
    class FakeRedis:
        async def eval(self, *args) -> int:
            return 0

    async def fake_start_workers(job_handler) -> None:
        return None

    async def fake_get_redis_client():
        return FakeRedis()

    async def fake_job_handler(bot, job) -> None:
        return None

    monkeypatch.setattr(reading_audio_queue, "start_audio_workers", fake_start_workers)
    monkeypatch.setattr(reading_audio_queue, "get_redis_client", fake_get_redis_client)

    with pytest.raises(asyncio.QueueFull):
        await reading_audio_queue.enqueue_redis_audio_job(
            reading_audio_queue.build_send_chunk_job(
                user_id=1,
                chat_id=1001,
                session_id="session-1",
                status_message_id=None,
            ),
            fake_job_handler,
        )


@pytest.mark.asyncio
async def test_enqueue_redis_audio_job_routes_prefetch_to_low_priority_queue(
    monkeypatch,
) -> None:
    captured = {}

    class FakeRedis:
        async def eval(
            self,
            script: str,
            keys_count: int,
            pending_key: str,
            processing_key: str,
            prefetch_pending_key: str,
            prefetch_processing_key: str,
            target_pending_key: str,
            max_size: str,
            value: str,
        ) -> int:
            captured["keys_count"] = keys_count
            captured["pending_key"] = pending_key
            captured["processing_key"] = processing_key
            captured["prefetch_pending_key"] = prefetch_pending_key
            captured["prefetch_processing_key"] = prefetch_processing_key
            captured["target_pending_key"] = target_pending_key
            captured["payload"] = value
            return 1

    async def fake_start_workers(job_handler) -> None:
        return None

    async def fake_get_redis_client():
        return FakeRedis()

    async def fake_job_handler(bot, job) -> None:
        return None

    monkeypatch.setattr(reading_audio_queue, "start_audio_workers", fake_start_workers)
    monkeypatch.setattr(reading_audio_queue, "get_redis_client", fake_get_redis_client)

    await reading_audio_queue.enqueue_redis_audio_job(
        reading_audio_queue.build_prefetch_chunk_job(
            user_id=1,
            session_id="session-1",
            chunk_index=1,
            chunk_text="next",
            voice="uk-UA-PolinaNeural",
            rate="+0%",
            provider_chain=["edge"],
        ),
        fake_job_handler,
    )

    payload = json.loads(captured["payload"])

    assert captured["keys_count"] == 5
    assert captured["pending_key"] == reading_audio_queue.READING_AUDIO_QUEUE_REDIS_KEY
    assert captured["processing_key"] == reading_audio_queue.REDIS_AUDIO_QUEUE_PROCESSING_KEY
    assert (
        captured["prefetch_pending_key"]
        == reading_audio_queue.REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY
    )
    assert (
        captured["prefetch_processing_key"]
        == reading_audio_queue.REDIS_PREFETCH_AUDIO_QUEUE_PROCESSING_KEY
    )
    assert (
        captured["target_pending_key"]
        == reading_audio_queue.REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY
    )
    assert payload["type"] == "prefetch_chunk"


@pytest.mark.asyncio
async def test_reading_service_redis_queue_compat_aliases_update_audio_queue(
    monkeypatch,
) -> None:
    captured = {}

    class FakeRedis:
        async def eval(
            self,
            script: str,
            keys_count: int,
            pending_key: str,
            processing_key: str,
            prefetch_pending_key: str,
            prefetch_processing_key: str,
            target_pending_key: str,
            max_size: str,
            value: str,
        ) -> int:
            captured["pending_key"] = pending_key
            captured["processing_key"] = processing_key
            captured["prefetch_pending_key"] = prefetch_pending_key
            captured["prefetch_processing_key"] = prefetch_processing_key
            captured["target_pending_key"] = target_pending_key
            captured["max_size"] = max_size
            captured["payload"] = value
            return 1

    async def fake_get_redis_client():
        return FakeRedis()

    monkeypatch.setattr(
        reading_service,
        "READING_AUDIO_QUEUE_REDIS_KEY",
        "test:compat:queue",
    )
    monkeypatch.setattr(reading_service, "READING_AUDIO_QUEUE_MAX_SIZE", 1)
    monkeypatch.setattr(
        reading_service,
        "_ensure_redis_audio_generation_worker",
        lambda: None,
    )
    monkeypatch.setattr(reading_audio_queue, "get_redis_client", fake_get_redis_client)

    await reading_service._enqueue_redis_audio_job(
        {
            "type": "send_chunk",
            "user_id": 1,
            "chat_id": 1001,
            "session_id": "legacy-session",
        }
    )

    payload = json.loads(captured["payload"])

    assert captured["pending_key"] == "test:compat:queue"
    assert captured["processing_key"] == "test:compat:queue:processing"
    assert captured["prefetch_pending_key"] == "test:compat:queue:prefetch"
    assert (
        captured["prefetch_processing_key"]
        == "test:compat:queue:prefetch:processing"
    )
    assert captured["target_pending_key"] == "test:compat:queue"
    assert captured["max_size"] == "1"
    assert payload["status_message_id"] is None
    assert payload["session_id"] == "legacy-session"


def test_serialize_audio_job_adds_unique_job_id() -> None:
    job = reading_audio_queue.build_send_chunk_job(
        user_id=1,
        chat_id=1001,
        session_id="session-1",
        status_message_id=None,
    )

    first = json.loads(reading_audio_queue.serialize_audio_job(job))
    second = json.loads(reading_audio_queue.serialize_audio_job(job))

    assert first["job_id"]
    assert second["job_id"]
    assert first["job_id"] != second["job_id"]


@pytest.mark.asyncio
async def test_requeue_interrupted_redis_audio_jobs(monkeypatch) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.processing = ["job-1", "job-2"]
            self.pending = []
            self.prefetch_processing = ["prefetch-job"]
            self.prefetch_pending = []

        async def rpoplpush(self, source: str, destination: str):
            if source == reading_audio_queue.REDIS_AUDIO_QUEUE_PROCESSING_KEY:
                assert destination == reading_audio_queue.READING_AUDIO_QUEUE_REDIS_KEY

                if not self.processing:
                    return None

                job = self.processing.pop()
                self.pending.insert(0, job)
                return job

            assert source == reading_audio_queue.REDIS_PREFETCH_AUDIO_QUEUE_PROCESSING_KEY
            assert destination == reading_audio_queue.REDIS_PREFETCH_AUDIO_QUEUE_REDIS_KEY

            if not self.prefetch_processing:
                return None

            job = self.prefetch_processing.pop()
            self.prefetch_pending.insert(0, job)
            return job

    fake_redis = FakeRedis()

    async def fake_get_redis_client():
        return fake_redis

    monkeypatch.setattr(reading_audio_queue, "get_redis_client", fake_get_redis_client)
    reading_audio_queue._redis_audio_queue_recovered = False

    moved_count = await reading_audio_queue.requeue_interrupted_redis_audio_jobs()

    assert moved_count == 3
    assert fake_redis.processing == []
    assert fake_redis.pending == ["job-1", "job-2"]
    assert fake_redis.prefetch_processing == []
    assert fake_redis.prefetch_pending == ["prefetch-job"]


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
            "index": 2,
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
async def test_cleanup_user_private_runtime_data_clears_session_and_queue(
    monkeypatch,
) -> None:
    async def fake_purge_queued_audio_jobs_for_user(user_id: int) -> int:
        assert user_id == 88
        return 2

    def fake_delete_user_audio_cache(user_id: int) -> dict[str, int]:
        assert user_id == 88
        return {
            "removed_files": 1,
            "removed_bytes": 1024,
            "owner_links_removed": 3,
        }

    monkeypatch.setattr(
        reading_service.privacy_service,
        "purge_queued_audio_jobs_for_user",
        fake_purge_queued_audio_jobs_for_user,
    )
    monkeypatch.setattr(
        reading_service.privacy_service,
        "delete_user_audio_cache",
        fake_delete_user_audio_cache,
    )

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
        "audio_cache_files": 1,
        "audio_cache_owner_links": 3,
    }
    assert await store.get_reading_session(88) is None
