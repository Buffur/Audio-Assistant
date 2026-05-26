import pytest
import pytest_asyncio
from redis.exceptions import RedisError

from services.reading.application import export_audio_service
from services.reading.application.commands import (
    ExportReadingAudioCommand,
    ExportReadingAudioNowCommand,
)
from services.reading.application.queue_orchestrator import (
    ReadingAudioQueueOrchestrator,
)
from services.reading.infrastructure import session_store
from texts.messages import EXPORT_AUDIO_CAPTION_TEXT, EXPORT_AUDIO_GENERATION_ERROR


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
    await session_store.cleanup_all_reading_sessions()
    yield
    await session_store.cleanup_all_reading_sessions()


@pytest.mark.asyncio
async def test_export_reading_audio_uses_injected_memory_runner() -> None:
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

    async def export_reading_audio_now(command: ExportReadingAudioNowCommand) -> None:
        captured["runner"] = command

    queued_jobs = []

    def enqueue_memory_audio_job(job) -> None:
        queued_jobs.append(job)

    await session_store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["one", "two"],
            "index": 0,
        },
    )

    message = FakeMessage()

    await export_audio_service.export_reading_audio(
        ExportReadingAudioCommand(message=message, user_id=1),
        cleanup_session=cleanup_session,
        finish_generation_if_session=finish_generation_if_session,
        queue_orchestrator=ReadingAudioQueueOrchestrator(
            use_redis_audio_queue=lambda: False,
            redis_audio_queue_position=redis_audio_queue_position,
            enqueue_redis_audio_job=enqueue_redis_audio_job,
            memory_audio_queue_position=lambda: 5,
            enqueue_memory_audio_job=enqueue_memory_audio_job,
        ),
        export_reading_audio_now=export_reading_audio_now,
    )
    await queued_jobs[0]()

    assert len(queued_jobs) == 1
    assert captured["runner"].message is message
    assert captured["runner"].user_id == 1
    assert captured["runner"].expected_session_id == "session-1"
    assert captured["runner"].status_msg in message.status_messages
    assert isinstance(captured["runner"].job_created_at, float)


@pytest.mark.asyncio
async def test_export_reading_audio_reports_redis_failure_without_memory_fallback() -> None:
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

    async def export_reading_audio_now(command: ExportReadingAudioNowCommand) -> None:
        raise AssertionError("failed Redis enqueue must not run export generation")

    await session_store.set_reading_session(
        user_id=2,
        session={
            "session_id": "session-redis",
            "chunks": ["one", "two"],
            "index": 0,
        },
    )

    message = FakeMessage()

    await export_audio_service.export_reading_audio(
        ExportReadingAudioCommand(message=message, user_id=2),
        cleanup_session=cleanup_session,
        finish_generation_if_session=finish_generation_if_session,
        queue_orchestrator=ReadingAudioQueueOrchestrator(
            use_redis_audio_queue=lambda: True,
            redis_audio_queue_position=redis_audio_queue_position,
            enqueue_redis_audio_job=enqueue_redis_audio_job,
            memory_audio_queue_position=memory_audio_queue_position,
            enqueue_memory_audio_job=enqueue_memory_audio_job,
        ),
        export_reading_audio_now=export_reading_audio_now,
    )

    assert captured["finish"] == (2, "session-redis")
    assert EXPORT_AUDIO_GENERATION_ERROR in message.answers
    assert message.status_messages[0].deleted is True


@pytest.mark.asyncio
async def test_export_reading_audio_now_generates_combines_and_sends(
    monkeypatch,
    workspace_tmp_path,
) -> None:
    captured = {}
    generated_paths = []
    combined_path = workspace_tmp_path / "combined.ogg"

    async def fake_get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+0%"

    async def fake_get_effective_user_tts_provider(user_id: int) -> str:
        return "edge"

    async def fake_generate_voice(**kwargs):
        audio_path = workspace_tmp_path / f"part-{len(generated_paths)}.ogg"
        audio_path.write_bytes(b"audio")
        generated_paths.append(audio_path)
        return [str(audio_path)]

    async def fake_concat_ogg_files(audio_files, smooth, crossfade_ms):
        captured["concat"] = {
            "audio_files": audio_files,
            "smooth": smooth,
            "crossfade_ms": crossfade_ms,
        }
        combined_path.write_bytes(b"combined")
        return str(combined_path)

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

    async def send_audio_files(**kwargs) -> None:
        captured["send"] = kwargs

    monkeypatch.setattr(
        export_audio_service,
        "get_effective_user_settings",
        fake_get_effective_user_settings,
    )
    monkeypatch.setattr(
        export_audio_service,
        "get_effective_user_tts_provider",
        fake_get_effective_user_tts_provider,
    )
    monkeypatch.setattr(export_audio_service, "generate_voice", fake_generate_voice)
    monkeypatch.setattr(export_audio_service, "concat_ogg_files", fake_concat_ogg_files)
    monkeypatch.setattr(
        export_audio_service,
        "select_voice_for_text",
        lambda text, voice_pref: "selected-voice",
    )

    await session_store.set_reading_session(
        user_id=3,
        session={
            "session_id": "session-export",
            "chunks": ["one", "two"],
            "index": 0,
            "is_generating": True,
        },
    )

    message = FakeMessage()
    status_msg = FakeStatusMessage("exporting")

    await export_audio_service.export_reading_audio_now(
        ExportReadingAudioNowCommand(
            message=message,
            user_id=3,
            expected_session_id="session-export",
            status_msg=status_msg,
            job_created_at=123.5,
        ),
        finish_generation_if_session=finish_generation_if_session,
        should_skip_deleted_user_job=should_skip_deleted_user_job,
        send_audio_files=send_audio_files,
    )

    session = await session_store.get_reading_session(3)

    assert session is not None
    assert session["is_generating"] is False
    assert captured["concat"]["audio_files"] == [str(path) for path in generated_paths]
    assert captured["send"]["audio_files"] == [str(combined_path)]
    assert captured["send"]["caption"] == EXPORT_AUDIO_CAPTION_TEXT
    assert captured["finish"] == (3, "session-export")
    assert status_msg.deleted is True
    assert all(not path.exists() for path in generated_paths)
