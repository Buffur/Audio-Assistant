import pytest
from redis.exceptions import RedisError

from services import reading_audio_queue


def test_audio_job_builders_preserve_redis_payload_contract() -> None:
    send_job = reading_audio_queue.build_send_chunk_job(
        user_id=1,
        chat_id=1001,
        session_id="session-1",
        status_message_id=42,
        created_at=123.5,
    )
    export_job = reading_audio_queue.build_export_audio_job(
        user_id=2,
        chat_id=1002,
        session_id="session-2",
        status_message_id=None,
        created_at=124.5,
    )
    prefetch_job = reading_audio_queue.build_prefetch_chunk_job(
        user_id=3,
        session_id="session-3",
        chunk_index=4,
        chunk_text="text",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        provider_chain=["edge"],
        created_at=125.5,
    )

    assert send_job == {
        "type": "send_chunk",
        "user_id": 1,
        "chat_id": 1001,
        "session_id": "session-1",
        "status_message_id": 42,
        "created_at": 123.5,
    }
    assert export_job == {
        "type": "export_audio",
        "user_id": 2,
        "chat_id": 1002,
        "session_id": "session-2",
        "status_message_id": None,
        "created_at": 124.5,
    }
    assert prefetch_job == {
        "type": "prefetch_chunk",
        "user_id": 3,
        "session_id": "session-3",
        "chunk_index": 4,
        "chunk_text": "text",
        "voice": "uk-UA-PolinaNeural",
        "rate": "+0%",
        "provider_chain": ["edge"],
        "created_at": 125.5,
    }


@pytest.mark.asyncio
async def test_audio_queue_stats_reports_memory_backend(monkeypatch) -> None:
    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_BACKEND", "memory")
    await reading_audio_queue.close_audio_queue(timeout_seconds=0.1)

    stats = await reading_audio_queue.get_audio_queue_stats()

    assert stats.as_dict() == {
        "backend": "memory",
        "max_size": reading_audio_queue.READING_AUDIO_QUEUE_MAX_SIZE,
        "pending": 0,
        "processing": 0,
        "worker_running": False,
        "degraded": False,
        "error": None,
        "is_full": False,
        "available_capacity": reading_audio_queue.READING_AUDIO_QUEUE_MAX_SIZE,
    }


@pytest.mark.asyncio
async def test_audio_queue_stats_reports_redis_backend(monkeypatch) -> None:
    class FakeRedis:
        async def llen(self, key: str) -> int:
            if key == reading_audio_queue.READING_AUDIO_QUEUE_REDIS_KEY:
                return 3

            if key == reading_audio_queue.REDIS_AUDIO_QUEUE_PROCESSING_KEY:
                return 1

            raise AssertionError(f"unexpected key: {key}")

    async def fake_get_redis_client():
        return FakeRedis()

    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_BACKEND", "redis")
    monkeypatch.setattr(reading_audio_queue, "get_redis_client", fake_get_redis_client)

    stats = await reading_audio_queue.get_audio_queue_stats()

    assert stats.backend == "redis"
    assert stats.pending == 3
    assert stats.processing == 1
    assert stats.is_full is False
    assert stats.available_capacity == reading_audio_queue.READING_AUDIO_QUEUE_MAX_SIZE - 3
    assert stats.degraded is False


@pytest.mark.asyncio
async def test_audio_queue_stats_degrades_on_redis_error(monkeypatch) -> None:
    class FakeRedis:
        async def llen(self, key: str) -> int:
            raise RedisError("redis down")

    async def fake_get_redis_client():
        return FakeRedis()

    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_BACKEND", "redis")
    monkeypatch.setattr(reading_audio_queue, "get_redis_client", fake_get_redis_client)

    stats = await reading_audio_queue.get_audio_queue_stats()

    assert stats.backend == "redis"
    assert stats.pending is None
    assert stats.processing is None
    assert stats.is_full is None
    assert stats.available_capacity is None
    assert stats.degraded is True
    assert stats.error == "RedisError"
