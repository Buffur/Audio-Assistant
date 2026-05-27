import asyncio

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


def test_validate_audio_job_accepts_builder_payload() -> None:
    job = reading_audio_queue.build_send_chunk_job(
        user_id=1,
        chat_id=1001,
        session_id="session-1",
        status_message_id=None,
    )

    assert reading_audio_queue.validate_audio_job(job) == job


def test_validate_audio_job_rejects_non_object() -> None:
    with pytest.raises(
        reading_audio_queue.InvalidAudioJobError,
        match="audio job must be an object",
    ):
        reading_audio_queue.validate_audio_job("not-json-object")


def test_validate_audio_job_rejects_missing_required_field() -> None:
    with pytest.raises(
        reading_audio_queue.InvalidAudioJobError,
        match="chat_id must be an integer",
    ):
        reading_audio_queue.validate_audio_job(
            {
                "type": "send_chunk",
                "user_id": 1,
                "session_id": "session-1",
                "status_message_id": None,
            },
        )


def test_validate_audio_job_rejects_invalid_optional_metadata() -> None:
    job = reading_audio_queue.build_export_audio_job(
        user_id=1,
        chat_id=1001,
        session_id="session-1",
        status_message_id=42,
    )
    job["created_at"] = "now"

    with pytest.raises(
        reading_audio_queue.InvalidAudioJobError,
        match="created_at must be a number",
    ):
        reading_audio_queue.validate_audio_job(job)


@pytest.mark.asyncio
async def test_enqueue_redis_audio_job_rejects_invalid_payload_before_side_effects(
    monkeypatch,
) -> None:
    async def fail_start_workers(job_handler) -> None:
        raise AssertionError("invalid payload must not start queue workers")

    async def fake_job_handler(bot, job) -> None:
        return None

    monkeypatch.setattr(reading_audio_queue, "start_audio_workers", fail_start_workers)

    with pytest.raises(reading_audio_queue.InvalidAudioJobError):
        await reading_audio_queue.enqueue_redis_audio_job(
            {
                "type": "send_chunk",
                "user_id": 1,
            },
            fake_job_handler,
        )


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
        "active": 0,
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
    assert stats.active == 4
    assert stats.is_full is False
    assert stats.available_capacity == reading_audio_queue.READING_AUDIO_QUEUE_MAX_SIZE - 4
    assert stats.degraded is False


@pytest.mark.asyncio
async def test_memory_audio_queue_backpressure_counts_processing_job(
    monkeypatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_job() -> None:
        started.set()
        await release.wait()

    async def extra_job() -> None:
        return None

    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_BACKEND", "memory")
    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_MAX_SIZE", 1)
    await reading_audio_queue.close_audio_queue(timeout_seconds=0.1)

    reading_audio_queue.enqueue_memory_audio_job(blocking_job)
    await asyncio.wait_for(started.wait(), timeout=1)

    stats = await reading_audio_queue.get_audio_queue_stats()

    assert stats.pending == 0
    assert stats.processing == 1
    assert stats.active == 1
    assert stats.is_full is True
    assert stats.available_capacity == 0
    assert reading_audio_queue.memory_audio_queue_position() == 2

    with pytest.raises(asyncio.QueueFull):
        reading_audio_queue.enqueue_memory_audio_job(extra_job)

    release.set()
    await reading_audio_queue.close_audio_queue(timeout_seconds=1.0)


@pytest.mark.asyncio
async def test_memory_audio_queue_serializes_same_user_without_starving_others(
    monkeypatch,
) -> None:
    started_user_one_first = asyncio.Event()
    release_user_one_first = asyncio.Event()
    started_user_one_second = asyncio.Event()
    started_user_two = asyncio.Event()
    execution_order: list[str] = []

    async def user_one_first_job() -> None:
        execution_order.append("user-1:first")
        started_user_one_first.set()
        await release_user_one_first.wait()

    async def user_one_second_job() -> None:
        execution_order.append("user-1:second")
        started_user_one_second.set()

    async def user_two_job() -> None:
        execution_order.append("user-2:first")
        started_user_two.set()

    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_BACKEND", "memory")
    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_WORKER_COUNT", 2)
    await reading_audio_queue.close_audio_queue(timeout_seconds=0.1)

    reading_audio_queue.enqueue_memory_audio_job(
        reading_audio_queue.set_audio_generation_job_user_id(
            user_one_first_job,
            1,
        )
    )
    await asyncio.wait_for(started_user_one_first.wait(), timeout=1)

    reading_audio_queue.enqueue_memory_audio_job(
        reading_audio_queue.set_audio_generation_job_user_id(
            user_one_second_job,
            1,
        )
    )
    reading_audio_queue.enqueue_memory_audio_job(
        reading_audio_queue.set_audio_generation_job_user_id(
            user_two_job,
            2,
        )
    )

    await asyncio.wait_for(started_user_two.wait(), timeout=1)

    assert started_user_one_second.is_set() is False
    assert execution_order == ["user-1:first", "user-2:first"]

    release_user_one_first.set()
    await asyncio.wait_for(started_user_one_second.wait(), timeout=1)

    assert execution_order == [
        "user-1:first",
        "user-2:first",
        "user-1:second",
    ]

    await reading_audio_queue.close_audio_queue(timeout_seconds=1.0)


@pytest.mark.asyncio
async def test_close_audio_queue_waits_for_active_redis_job(monkeypatch) -> None:
    payload = reading_audio_queue.serialize_audio_job(
        reading_audio_queue.build_send_chunk_job(
            user_id=1,
            chat_id=1001,
            session_id="session-1",
            status_message_id=None,
        )
    )
    started = asyncio.Event()
    release = asyncio.Event()
    closed_sessions = []

    class FakeSession:
        async def close(self) -> None:
            closed_sessions.append(True)

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token
            self.session = FakeSession()

    class FakeRedis:
        def __init__(self) -> None:
            self.pending = [payload]
            self.processing = []

        async def brpoplpush(
            self,
            source: str,
            destination: str,
            timeout: int,
        ):
            assert source == reading_audio_queue.READING_AUDIO_QUEUE_REDIS_KEY
            assert destination == reading_audio_queue.REDIS_AUDIO_QUEUE_PROCESSING_KEY

            if not self.pending:
                await asyncio.sleep(0.01)
                return None

            raw_job = self.pending.pop()
            self.processing.insert(0, raw_job)
            return raw_job

        async def lrem(self, key: str, count: int, value: str) -> int:
            assert key == reading_audio_queue.REDIS_AUDIO_QUEUE_PROCESSING_KEY
            self.processing.remove(value)
            return 1

        async def eval(self, *args):
            raise AssertionError("graceful shutdown must not requeue finished jobs")

    fake_redis = FakeRedis()

    async def fake_get_redis_client():
        return fake_redis

    async def fake_job_handler(bot, job) -> None:
        started.set()
        await release.wait()

    monkeypatch.setattr(reading_audio_queue, "Bot", FakeBot)
    monkeypatch.setattr(reading_audio_queue, "get_redis_client", fake_get_redis_client)

    reading_audio_queue._ensure_redis_audio_generation_worker(fake_job_handler)
    await asyncio.wait_for(started.wait(), timeout=1)

    close_task = asyncio.create_task(
        reading_audio_queue.close_audio_queue(timeout_seconds=1.0)
    )
    await asyncio.sleep(0)

    assert close_task.done() is False

    release.set()
    await asyncio.wait_for(close_task, timeout=1)

    assert fake_redis.pending == []
    assert fake_redis.processing == []
    assert closed_sessions == [True, True]


@pytest.mark.asyncio
async def test_redis_audio_workers_defer_same_user_job_and_process_other_user(
    monkeypatch,
) -> None:
    first_payload = reading_audio_queue.serialize_audio_job(
        reading_audio_queue.build_send_chunk_job(
            user_id=1,
            chat_id=1001,
            session_id="user-1:first",
            status_message_id=None,
        )
    )
    second_payload = reading_audio_queue.serialize_audio_job(
        reading_audio_queue.build_send_chunk_job(
            user_id=1,
            chat_id=1001,
            session_id="user-1:second",
            status_message_id=None,
        )
    )
    other_user_payload = reading_audio_queue.serialize_audio_job(
        reading_audio_queue.build_send_chunk_job(
            user_id=2,
            chat_id=1002,
            session_id="user-2:first",
            status_message_id=None,
        )
    )
    started_user_one_first = asyncio.Event()
    release_user_one_first = asyncio.Event()
    started_user_one_second = asyncio.Event()
    started_user_two = asyncio.Event()
    execution_order: list[str] = []
    closed_sessions = []

    class FakeSession:
        async def close(self) -> None:
            closed_sessions.append(True)

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token
            self.session = FakeSession()

    class FakeRedis:
        def __init__(self) -> None:
            self.pending = [
                other_user_payload,
                second_payload,
                first_payload,
            ]
            self.processing = []

        async def brpoplpush(
            self,
            source: str,
            destination: str,
            timeout: int,
        ):
            if not self.pending:
                await asyncio.sleep(0.01)
                return None

            raw_job = self.pending.pop()
            self.processing.insert(0, raw_job)
            return raw_job

        async def lrem(self, key: str, count: int, value: str) -> int:
            self.processing.remove(value)
            return 1

        async def eval(self, *args):
            raise AssertionError("no active Redis jobs should need requeue")

    fake_redis = FakeRedis()

    async def fake_get_redis_client():
        return fake_redis

    async def fake_job_handler(bot, job) -> None:
        execution_order.append(job["session_id"])

        if job["session_id"] == "user-1:first":
            started_user_one_first.set()
            await release_user_one_first.wait()
            return

        if job["session_id"] == "user-1:second":
            started_user_one_second.set()
            return

        if job["session_id"] == "user-2:first":
            started_user_two.set()
            return

    monkeypatch.setattr(reading_audio_queue, "Bot", FakeBot)
    monkeypatch.setattr(reading_audio_queue, "get_redis_client", fake_get_redis_client)
    monkeypatch.setattr(reading_audio_queue, "READING_AUDIO_QUEUE_WORKER_COUNT", 2)

    reading_audio_queue._ensure_redis_audio_generation_worker(fake_job_handler)
    await asyncio.wait_for(started_user_one_first.wait(), timeout=1)
    await asyncio.wait_for(started_user_two.wait(), timeout=1)

    assert started_user_one_second.is_set() is False
    assert execution_order == ["user-1:first", "user-2:first"]

    release_user_one_first.set()
    await asyncio.wait_for(started_user_one_second.wait(), timeout=1)

    assert execution_order == [
        "user-1:first",
        "user-2:first",
        "user-1:second",
    ]
    assert fake_redis.pending == []
    assert fake_redis.processing == []

    await reading_audio_queue.close_audio_queue(timeout_seconds=1.0)
    assert closed_sessions == [True, True]


@pytest.mark.asyncio
async def test_close_audio_queue_requeues_active_redis_job_after_timeout(
    monkeypatch,
) -> None:
    payload = reading_audio_queue.serialize_audio_job(
        reading_audio_queue.build_send_chunk_job(
            user_id=1,
            chat_id=1001,
            session_id="session-1",
            status_message_id=None,
        )
    )
    started = asyncio.Event()
    closed_sessions = []

    class FakeSession:
        async def close(self) -> None:
            closed_sessions.append(True)

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token
            self.session = FakeSession()

    class FakeRedis:
        def __init__(self) -> None:
            self.pending = [payload]
            self.processing = []
            self.requeued = []

        async def brpoplpush(
            self,
            source: str,
            destination: str,
            timeout: int,
        ):
            if not self.pending:
                await asyncio.sleep(0.01)
                return None

            raw_job = self.pending.pop()
            self.processing.insert(0, raw_job)
            return raw_job

        async def lrem(self, key: str, count: int, value: str) -> int:
            self.processing.remove(value)
            return 1

        async def eval(
            self,
            script: str,
            keys_count: int,
            processing_key: str,
            pending_key: str,
            raw_job: str,
        ) -> int:
            assert keys_count == 2
            assert processing_key == reading_audio_queue.REDIS_AUDIO_QUEUE_PROCESSING_KEY
            assert pending_key == reading_audio_queue.READING_AUDIO_QUEUE_REDIS_KEY

            if raw_job not in self.processing:
                return 0

            self.processing.remove(raw_job)
            self.pending.insert(0, raw_job)
            self.requeued.append(raw_job)
            return 1

    fake_redis = FakeRedis()
    never_release = asyncio.Event()

    async def fake_get_redis_client():
        return fake_redis

    async def fake_job_handler(bot, job) -> None:
        started.set()
        await never_release.wait()

    monkeypatch.setattr(reading_audio_queue, "Bot", FakeBot)
    monkeypatch.setattr(reading_audio_queue, "get_redis_client", fake_get_redis_client)

    reading_audio_queue._ensure_redis_audio_generation_worker(fake_job_handler)
    await asyncio.wait_for(started.wait(), timeout=1)

    await reading_audio_queue.close_audio_queue(timeout_seconds=0.01)

    assert fake_redis.pending == [payload]
    assert fake_redis.processing == []
    assert fake_redis.requeued == [payload]
    assert closed_sessions == [True, True]


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
    assert stats.active is None
    assert stats.is_full is None
    assert stats.available_capacity is None
    assert stats.degraded is True
    assert stats.error == "RedisError"
