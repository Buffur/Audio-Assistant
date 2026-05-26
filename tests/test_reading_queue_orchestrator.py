import pytest
from redis.exceptions import RedisError

from services.reading.application.commands import SendAudioChunkNowCommand
from services.reading.application.queue_orchestrator import (
    PrefetchAudioEnqueueCommand,
    ReadingAudioQueueOrchestrator,
    SendChunkAudioEnqueueCommand,
)


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
async def test_prefetch_memory_path_returns_created_task() -> None:
    async def redis_audio_queue_position() -> int:
        raise AssertionError("memory prefetch must not read Redis queue position")

    async def enqueue_redis_audio_job(job) -> None:
        raise AssertionError("memory prefetch must not enqueue Redis job")

    orchestrator = ReadingAudioQueueOrchestrator(
        use_redis_audio_queue=lambda: False,
        redis_audio_queue_position=redis_audio_queue_position,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=lambda: 0,
        enqueue_memory_audio_job=lambda job: None,
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
    assert await result.memory_task == ["prefetch.ogg"]
