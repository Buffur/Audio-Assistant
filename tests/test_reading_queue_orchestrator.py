import pytest
from redis.exceptions import RedisError

from services.reading.application.commands import (
    ExportReadingAudioNowCommand,
    SendAudioChunkNowCommand,
)
from services.reading.application.queue_orchestrator import (
    ExportAudioEnqueueCommand,
    PrefetchAudioEnqueueCommand,
    ReadingAudioQueueOrchestrator,
    SendChunkAudioEnqueueCommand,
)
from services.reading.audio_queue import AudioQueueStats


class FakeStatusMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.message_id = 42


class FakeMessage:
    def __init__(self) -> None:
        self.status_messages: list[FakeStatusMessage] = []
        self.chat = type("FakeChat", (), {"id": 1001})()

    async def answer(self, text: str, **kwargs):
        status = FakeStatusMessage(text)
        self.status_messages.append(status)
        return status


def queue_stats(
    *,
    backend: str,
    max_size: int = 20,
    pending: int | None = 0,
    processing: int | None = 0,
    degraded: bool = False,
    error: str | None = None,
) -> AudioQueueStats:
    return AudioQueueStats(
        backend=backend,
        max_size=max_size,
        pending=pending,
        processing=processing,
        worker_running=True,
        degraded=degraded,
        error=error,
    )


async def healthy_memory_queue_stats() -> AudioQueueStats:
    return queue_stats(backend="memory")


async def healthy_redis_queue_stats() -> AudioQueueStats:
    return queue_stats(backend="redis")


@pytest.mark.asyncio
async def test_send_chunk_memory_path_wraps_typed_run_command() -> None:
    captured = {}
    queued_jobs = []

    async def run_now(command: SendAudioChunkNowCommand) -> None:
        captured["run_now"] = command

    async def redis_audio_queue_position() -> int:
        raise AssertionError("memory path must not read Redis queue position")

    async def enqueue_redis_audio_job(job) -> None:
        raise AssertionError("memory path must not enqueue Redis job")

    def enqueue_memory_audio_job(job) -> None:
        queued_jobs.append(job)

    orchestrator = ReadingAudioQueueOrchestrator(
        use_redis_audio_queue=lambda: False,
        redis_audio_queue_position=redis_audio_queue_position,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=lambda: 3,
        enqueue_memory_audio_job=enqueue_memory_audio_job,
        get_queue_stats=healthy_memory_queue_stats,
    )
    message = FakeMessage()

    result = await orchestrator.enqueue_send_chunk_audio(
        SendChunkAudioEnqueueCommand(
            message=message,
            user_id=7,
            session_id="session-1",
            current_part=1,
            total_parts=2,
            run_now=run_now,
        )
    )
    await queued_jobs[0]()

    assert result.queued is True
    assert result.backend == "memory"
    assert result.status_msg in message.status_messages
    assert captured["run_now"].user_id == 7
    assert captured["run_now"].expected_session_id == "session-1"
    assert captured["run_now"].status_msg is result.status_msg
    assert isinstance(captured["run_now"].job_created_at, float)


@pytest.mark.asyncio
async def test_send_chunk_redis_path_builds_serialized_job() -> None:
    captured = {}

    async def redis_audio_queue_position() -> int:
        return 5

    async def enqueue_redis_audio_job(job) -> None:
        captured.update(job)

    def enqueue_memory_audio_job(job) -> None:
        raise AssertionError("Redis path must not enqueue memory job")

    async def run_now(command: SendAudioChunkNowCommand) -> None:
        raise AssertionError("Redis path must not run memory command")

    orchestrator = ReadingAudioQueueOrchestrator(
        use_redis_audio_queue=lambda: True,
        redis_audio_queue_position=redis_audio_queue_position,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=lambda: 0,
        enqueue_memory_audio_job=enqueue_memory_audio_job,
        get_queue_stats=healthy_redis_queue_stats,
    )
    message = FakeMessage()

    result = await orchestrator.enqueue_send_chunk_audio(
        SendChunkAudioEnqueueCommand(
            message=message,
            user_id=8,
            session_id="session-redis",
            current_part=1,
            total_parts=3,
            run_now=run_now,
        )
    )
    created_at = captured.pop("created_at")

    assert result.queued is True
    assert result.backend == "redis"
    assert isinstance(created_at, float)
    assert captured == {
        "type": "send_chunk",
        "user_id": 8,
        "chat_id": 1001,
        "session_id": "session-redis",
        "status_message_id": 42,
    }


@pytest.mark.asyncio
async def test_send_chunk_redis_failure_does_not_fallback_to_memory() -> None:
    async def redis_audio_queue_position() -> int:
        return 1

    async def enqueue_redis_audio_job(job) -> None:
        raise RedisError("redis down")

    def enqueue_memory_audio_job(job) -> None:
        raise AssertionError("Redis failure must not fallback to memory")

    async def run_now(command: SendAudioChunkNowCommand) -> None:
        raise AssertionError("Redis failure must not run memory command")

    orchestrator = ReadingAudioQueueOrchestrator(
        use_redis_audio_queue=lambda: True,
        redis_audio_queue_position=redis_audio_queue_position,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=lambda: 0,
        enqueue_memory_audio_job=enqueue_memory_audio_job,
        get_queue_stats=healthy_redis_queue_stats,
    )
    message = FakeMessage()

    result = await orchestrator.enqueue_send_chunk_audio(
        SendChunkAudioEnqueueCommand(
            message=message,
            user_id=9,
            session_id="session-fail",
            current_part=1,
            total_parts=1,
            run_now=run_now,
        )
    )

    assert result.queued is False
    assert result.status == "failed"
    assert result.backend == "redis"
    assert isinstance(result.error, RedisError)
    assert result.status_msg in message.status_messages


@pytest.mark.asyncio
async def test_send_chunk_memory_backpressure_rejects_before_enqueue() -> None:
    async def get_queue_stats() -> AudioQueueStats:
        return queue_stats(
            backend="memory",
            max_size=2,
            pending=1,
            processing=1,
        )

    async def redis_audio_queue_position() -> int:
        raise AssertionError("memory path must not read Redis queue position")

    async def enqueue_redis_audio_job(job) -> None:
        raise AssertionError("memory path must not enqueue Redis job")

    def memory_audio_queue_position() -> int:
        raise AssertionError("full memory queue must not compute queue position")

    def enqueue_memory_audio_job(job) -> None:
        raise AssertionError("full memory queue must not enqueue job")

    async def run_now(command: SendAudioChunkNowCommand) -> None:
        raise AssertionError("full memory queue must not run command")

    orchestrator = ReadingAudioQueueOrchestrator(
        use_redis_audio_queue=lambda: False,
        redis_audio_queue_position=redis_audio_queue_position,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=memory_audio_queue_position,
        enqueue_memory_audio_job=enqueue_memory_audio_job,
        get_queue_stats=get_queue_stats,
    )
    message = FakeMessage()

    result = await orchestrator.enqueue_send_chunk_audio(
        SendChunkAudioEnqueueCommand(
            message=message,
            user_id=11,
            session_id="session-memory-full",
            current_part=1,
            total_parts=1,
            run_now=run_now,
        )
    )

    assert result.queued is False
    assert result.status == "full"
    assert result.backend == "memory"
    assert result.queue_stats is not None
    assert result.queue_stats.active == 2
    assert result.queue_stats.available_capacity == 0
    assert message.status_messages == []


@pytest.mark.asyncio
async def test_send_chunk_redis_degraded_stats_fail_without_memory_fallback() -> None:
    async def get_queue_stats() -> AudioQueueStats:
        return queue_stats(
            backend="redis",
            max_size=20,
            pending=None,
            processing=None,
            degraded=True,
            error="RedisError",
        )

    async def redis_audio_queue_position() -> int:
        raise AssertionError("degraded Redis stats must stop before position lookup")

    async def enqueue_redis_audio_job(job) -> None:
        raise AssertionError("degraded Redis stats must stop before enqueue")

    def enqueue_memory_audio_job(job) -> None:
        raise AssertionError("degraded Redis must not fallback to memory")

    async def run_now(command: SendAudioChunkNowCommand) -> None:
        raise AssertionError("degraded Redis must not run memory command")

    orchestrator = ReadingAudioQueueOrchestrator(
        use_redis_audio_queue=lambda: True,
        redis_audio_queue_position=redis_audio_queue_position,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=lambda: 0,
        enqueue_memory_audio_job=enqueue_memory_audio_job,
        get_queue_stats=get_queue_stats,
    )
    message = FakeMessage()

    result = await orchestrator.enqueue_send_chunk_audio(
        SendChunkAudioEnqueueCommand(
            message=message,
            user_id=12,
            session_id="session-redis-degraded",
            current_part=1,
            total_parts=1,
            run_now=run_now,
        )
    )

    assert result.queued is False
    assert result.status == "failed"
    assert result.backend == "redis"
    assert result.queue_stats is not None
    assert result.queue_stats.degraded is True
    assert message.status_messages == []


@pytest.mark.asyncio
async def test_export_audio_redis_backpressure_rejects_full_queue() -> None:
    async def get_queue_stats() -> AudioQueueStats:
        return queue_stats(
            backend="redis",
            max_size=2,
            pending=1,
            processing=1,
        )

    async def redis_audio_queue_position() -> int:
        raise AssertionError("full Redis queue must stop before position lookup")

    async def enqueue_redis_audio_job(job) -> None:
        raise AssertionError("full Redis queue must not enqueue job")

    def enqueue_memory_audio_job(job) -> None:
        raise AssertionError("full Redis queue must not fallback to memory")

    async def run_now(command: ExportReadingAudioNowCommand) -> None:
        raise AssertionError("full Redis queue must not run memory command")

    orchestrator = ReadingAudioQueueOrchestrator(
        use_redis_audio_queue=lambda: True,
        redis_audio_queue_position=redis_audio_queue_position,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=lambda: 0,
        enqueue_memory_audio_job=enqueue_memory_audio_job,
        get_queue_stats=get_queue_stats,
    )
    message = FakeMessage()

    result = await orchestrator.enqueue_export_audio(
        ExportAudioEnqueueCommand(
            message=message,
            user_id=13,
            session_id="session-export-full",
            total_parts=3,
            run_now=run_now,
        )
    )

    assert result.queued is False
    assert result.status == "full"
    assert result.backend == "redis"
    assert result.queue_stats is not None
    assert result.queue_stats.is_full is True
    assert message.status_messages == []


@pytest.mark.asyncio
async def test_prefetch_redis_backpressure_rejects_full_queue() -> None:
    async def get_queue_stats() -> AudioQueueStats:
        return queue_stats(
            backend="redis",
            max_size=2,
            pending=1,
            processing=1,
        )

    async def enqueue_redis_audio_job(job) -> None:
        raise AssertionError("full Redis prefetch queue must not enqueue job")

    async def memory_audio_job() -> list[str]:
        raise AssertionError("full Redis prefetch queue must not run memory job")

    orchestrator = ReadingAudioQueueOrchestrator(
        use_redis_audio_queue=lambda: True,
        redis_audio_queue_position=lambda: 0,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=lambda: 0,
        enqueue_memory_audio_job=lambda job: None,
        get_queue_stats=get_queue_stats,
    )

    result = await orchestrator.enqueue_prefetch_audio(
        PrefetchAudioEnqueueCommand(
            user_id=14,
            session_id="session-prefetch-full",
            chunk_index=1,
            chunk_text="next",
            voice="voice",
            rate="+0%",
            provider_chain=["edge"],
            memory_audio_job=memory_audio_job,
        )
    )

    assert result.queued is False
    assert result.status == "full"
    assert result.backend == "redis"
    assert result.queue_stats is not None
    assert result.queue_stats.active == 2


@pytest.mark.asyncio
async def test_prefetch_memory_path_returns_created_task() -> None:
    queued_jobs = []

    async def redis_audio_queue_position() -> int:
        raise AssertionError("memory prefetch must not read Redis queue position")

    async def enqueue_redis_audio_job(job) -> None:
        raise AssertionError("memory prefetch must not enqueue Redis job")

    orchestrator = ReadingAudioQueueOrchestrator(
        use_redis_audio_queue=lambda: False,
        redis_audio_queue_position=redis_audio_queue_position,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=lambda: 0,
        enqueue_memory_audio_job=lambda job: queued_jobs.append(job),
        get_queue_stats=healthy_memory_queue_stats,
    )

    async def memory_audio_job() -> list[str]:
        return ["prefetch.ogg"]

    result = await orchestrator.enqueue_prefetch_audio(
        PrefetchAudioEnqueueCommand(
            user_id=10,
            session_id="session-prefetch",
            chunk_index=1,
            chunk_text="next chunk",
            voice="voice",
            rate="+0%",
            provider_chain=["edge"],
            memory_audio_job=memory_audio_job,
        )
    )

    assert result.queued is True
    assert result.backend == "memory"
    assert result.memory_task is not None
    await queued_jobs[0]()
    assert await result.memory_task == ["prefetch.ogg"]
