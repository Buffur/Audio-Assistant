import asyncio
import json
import os

import pytest
import pytest_asyncio
from redis.exceptions import RedisError

from services import reading_service
from services import reading_session_store as store
from services import redis_client


@pytest_asyncio.fixture()
async def redis_test_client(monkeypatch):
    redis_url = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")

    monkeypatch.setattr(redis_client, "REDIS_URL", redis_url)

    await redis_client.close_redis_client()
    client = await redis_client.get_redis_client()

    try:
        await client.ping()
    except RedisError as error:
        await redis_client.close_redis_client()
        pytest.skip(f"Redis is not available for integration tests: {error}")

    await client.flushdb()

    try:
        yield client
    finally:
        await client.flushdb()
        await redis_client.close_redis_client()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_reading_session_roundtrip_and_generation_lock(
    redis_test_client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(store, "READING_SESSION_BACKEND", "redis")

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "redis-session",
            "chunks": ["one", "two"],
            "index": 0,
            "is_generating": False,
            "summary_text": "summary",
        },
    )

    session = await store.get_reading_session(1)

    assert session["session_id"] == "redis-session"
    assert session["chunks"] == ["one", "two"]
    assert session["summary_text"] == "summary"

    assert await store.try_start_generation(1) is True
    assert await store.try_start_generation(1) is False

    await store.finish_generation(1)
    await store.update_reading_session(1, index=1, summary_delivered=True)

    updated_session = await store.get_reading_session(1)

    assert updated_session["index"] == 1
    assert updated_session["is_generating"] is False
    assert updated_session["summary_delivered"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_audio_queue_pushes_serialized_jobs_and_enforces_max_size(
    redis_test_client,
    monkeypatch,
) -> None:
    queue_key = "test:reading:audio:queue"

    monkeypatch.setattr(reading_service, "READING_AUDIO_QUEUE_REDIS_KEY", queue_key)
    monkeypatch.setattr(reading_service, "READING_AUDIO_QUEUE_MAX_SIZE", 1)
    monkeypatch.setattr(
        reading_service,
        "_ensure_redis_audio_generation_worker",
        lambda: None,
    )

    await reading_service._enqueue_redis_audio_job({
        "type": "send_chunk",
        "user_id": 1,
        "chat_id": 100,
        "session_id": "redis-session",
    })

    assert await redis_test_client.llen(queue_key) == 1

    raw_job = await redis_test_client.lindex(queue_key, 0)
    job = json.loads(raw_job)

    assert job["type"] == "send_chunk"
    assert job["user_id"] == 1
    assert job["session_id"] == "redis-session"
    assert "created_at" in job

    with pytest.raises(asyncio.QueueFull):
        await reading_service._enqueue_redis_audio_job({
            "type": "send_chunk",
            "user_id": 2,
            "chat_id": 100,
            "session_id": "redis-session-2",
        })


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_audio_queue_purge_removes_only_target_user_jobs(
    redis_test_client,
    monkeypatch,
) -> None:
    queue_key = "test:reading:audio:queue:purge"

    monkeypatch.setattr(reading_service, "READING_AUDIO_QUEUE_BACKEND", "redis")
    monkeypatch.setattr(reading_service, "READING_AUDIO_QUEUE_REDIS_KEY", queue_key)
    monkeypatch.setattr(reading_service, "READING_AUDIO_QUEUE_MAX_SIZE", 10)
    monkeypatch.setattr(
        reading_service,
        "_ensure_redis_audio_generation_worker",
        lambda: None,
    )

    await reading_service._enqueue_redis_audio_job({
        "type": "send_chunk",
        "user_id": 1,
        "chat_id": 100,
        "session_id": "user-1-a",
    })
    await reading_service._enqueue_redis_audio_job({
        "type": "export_audio",
        "user_id": 2,
        "chat_id": 200,
        "session_id": "user-2",
    })
    await reading_service._enqueue_redis_audio_job({
        "type": "send_chunk",
        "user_id": 1,
        "chat_id": 100,
        "session_id": "user-1-b",
    })
    await redis_test_client.rpush(queue_key, "not-json")

    removed_count = await reading_service.purge_queued_audio_jobs_for_user(1)

    remaining_raw_jobs = await redis_test_client.lrange(queue_key, 0, -1)
    remaining_jobs = [
        json.loads(raw_job)
        for raw_job in remaining_raw_jobs
        if raw_job != "not-json"
    ]

    assert removed_count == 2
    assert len(remaining_raw_jobs) == 2
    assert remaining_jobs[0]["user_id"] == 2
    assert remaining_raw_jobs[-1] == "not-json"
