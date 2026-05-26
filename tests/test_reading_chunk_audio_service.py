import pytest
import pytest_asyncio
from redis.exceptions import RedisError

from services.reading.application import chunk_audio_service
from services.reading.application.commands import (
    AudioFilesResult,
    SendAudioChunkCommand,
    SendAudioChunkNowCommand,
)
from services.reading.infrastructure import session_store
from texts.messages import BACKGROUND_GENERATION_ERROR


class FakeStatusMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.deleted = False
        self.message_id = 42

    async def edit_text(self, text: str) -> None:
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
    await session_store.cleanup_all_reading_sessions()
    yield
    await session_store.cleanup_all_reading_sessions()


@pytest.mark.asyncio
async def test_send_audio_chunk_uses_injected_memory_runner() -> None:
    captured = {}

    async def cleanup_session(user_id: int) -> None:
        captured["cleanup"] = user_id

    async def finish_generation_if_session(
        user_id: int,
        session_id: str | None,
    ) -> None:
        captured["finish"] = (user_id, session_id)

    async def redis_audio_queue_position() -> int:
        raise AssertionError("memory path must not ask Redis for queue position")

    async def enqueue_redis_audio_job(job) -> None:
        raise AssertionError("memory path must not enqueue Redis job")

    async def send_audio_chunk_now(command: SendAudioChunkNowCommand) -> None:
        captured["runner"] = command

    queued_jobs = []

    def enqueue_memory_audio_job(job) -> None:
        queued_jobs.append(job)

    await session_store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["one"],
            "index": 0,
        },
    )

    message = FakeMessage()

    await chunk_audio_service.send_audio_chunk(
        SendAudioChunkCommand(message=message, user_id=1),
        cleanup_session=cleanup_session,
        finish_generation_if_session=finish_generation_if_session,
        use_redis_audio_queue=lambda: False,
        redis_audio_queue_position=redis_audio_queue_position,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=lambda: 3,
        enqueue_memory_audio_job=enqueue_memory_audio_job,
        send_audio_chunk_now=send_audio_chunk_now,
    )
    await queued_jobs[0]()

    assert len(queued_jobs) == 1
    assert captured["runner"].message is message
    assert captured["runner"].user_id == 1
    assert captured["runner"].expected_session_id == "session-1"
    assert captured["runner"].status_msg in message.status_messages
    assert isinstance(captured["runner"].job_created_at, float)


@pytest.mark.asyncio
async def test_send_audio_chunk_reports_redis_failure_without_memory_fallback() -> None:
    captured = {}

    async def cleanup_session(user_id: int) -> None:
        captured["cleanup"] = user_id

    async def finish_generation_if_session(
        user_id: int,
        session_id: str | None,
    ) -> None:
        captured["finish"] = (user_id, session_id)

    async def redis_audio_queue_position() -> int:
        return 1

    async def enqueue_redis_audio_job(job) -> None:
        raise RedisError("redis down")

    def memory_audio_queue_position() -> int:
        raise AssertionError("Redis failure must not fall back to memory queue")

    def enqueue_memory_audio_job(job) -> None:
        raise AssertionError("Redis failure must not enqueue memory job")

    async def send_audio_chunk_now(command: SendAudioChunkNowCommand) -> None:
        raise AssertionError("failed Redis enqueue must not run chunk generation")

    await session_store.set_reading_session(
        user_id=2,
        session={
            "session_id": "session-redis",
            "chunks": ["one"],
            "index": 0,
        },
    )

    message = FakeMessage()

    await chunk_audio_service.send_audio_chunk(
        SendAudioChunkCommand(message=message, user_id=2),
        cleanup_session=cleanup_session,
        finish_generation_if_session=finish_generation_if_session,
        use_redis_audio_queue=lambda: True,
        redis_audio_queue_position=redis_audio_queue_position,
        enqueue_redis_audio_job=enqueue_redis_audio_job,
        memory_audio_queue_position=memory_audio_queue_position,
        enqueue_memory_audio_job=enqueue_memory_audio_job,
        send_audio_chunk_now=send_audio_chunk_now,
    )

    assert captured["finish"] == (2, "session-redis")
    assert BACKGROUND_GENERATION_ERROR in message.answers
    assert message.status_messages[0].deleted is True


@pytest.mark.asyncio
async def test_send_audio_chunk_now_sends_audio_and_starts_prefetch() -> None:
    captured = {}

    async def cleanup_session(user_id: int) -> None:
        captured["cleanup"] = user_id

    async def finish_generation_if_session(
        user_id: int,
        session_id: str | None,
    ) -> None:
        captured["finish"] = (user_id, session_id)
        await session_store.update_reading_session(user_id, is_generating=False)

    async def should_skip_deleted_user_job(
        user_id: int,
        job_created_at: float | None,
    ) -> bool:
        return False

    async def get_audio_from_prefetch_or_generate(command):
        captured["audio_request"] = command
        return AudioFilesResult(audio_files=["chunk.ogg"])

    async def start_prefetch_next_chunk(command) -> None:
        captured["prefetch"] = command

    async def send_audio_files(**kwargs) -> None:
        captured["send"] = kwargs

    async def get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+0%"

    async def get_effective_user_tts_provider(user_id: int) -> str:
        return "edge"

    async def is_premium_user(user_id: int) -> bool:
        return False

    await session_store.set_reading_session(
        user_id=3,
        session={
            "session_id": "session-flow",
            "chunks": ["current", "next"],
            "index": 0,
            "is_generating": True,
        },
    )

    message = FakeMessage()

    await chunk_audio_service.send_audio_chunk_now(
        SendAudioChunkNowCommand(
            message=message,
            user_id=3,
            expected_session_id="session-flow",
            status_msg=None,
            job_created_at=123.5,
        ),
        cleanup_session=cleanup_session,
        finish_generation_if_session=finish_generation_if_session,
        should_skip_deleted_user_job=should_skip_deleted_user_job,
        get_audio_from_prefetch_or_generate=get_audio_from_prefetch_or_generate,
        start_prefetch_next_chunk=start_prefetch_next_chunk,
        send_audio_files=send_audio_files,
        get_effective_user_settings=get_effective_user_settings,
        get_effective_user_tts_provider=get_effective_user_tts_provider,
        is_premium_user=is_premium_user,
        select_voice_for_text=lambda text, voice_pref: "selected-voice",
    )

    session = await session_store.get_reading_session(3)

    assert session is not None
    assert session["index"] == 1
    assert session["is_generating"] is False
    assert captured["audio_request"].chunk_text == "current"
    assert captured["send"]["audio_files"] == ["chunk.ogg"]
    assert captured["prefetch"].next_index == 1
    assert captured["finish"] == (3, "session-flow")
