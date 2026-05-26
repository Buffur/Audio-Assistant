import asyncio

import pytest
import pytest_asyncio

from services.reading import audio_queue
from services.reading.application import prefetch_service
from services.reading.application.commands import (
    PrefetchAudioJobCommand,
    ResolvePrefetchedAudioCommand,
    StartPrefetchCommand,
)
from services.reading.application.queue_orchestrator import (
    ReadingAudioQueueOrchestrator,
)
from services.reading.infrastructure import session_store


class FakeStatusMessage:
    def __init__(self) -> None:
        self.edits: list[str] = []
        self.deleted = False

    async def edit_text(self, text: str) -> None:
        self.edits.append(text)

    async def delete(self) -> None:
        self.deleted = True


@pytest_asyncio.fixture(autouse=True)
async def cleanup_reading_state():
    await session_store.cleanup_all_reading_sessions()
    yield
    await session_store.cleanup_all_reading_sessions()


@pytest.mark.asyncio
async def test_run_prefetch_audio_job_marks_session_ready(monkeypatch) -> None:
    async def fake_generate_voice(**kwargs):
        assert kwargs["text"] == "next chunk"
        assert kwargs["voice"] == "uk-UA-PolinaNeural"
        assert kwargs["rate"] == "+0%"
        assert kwargs["provider_chain"] == ["edge"]
        return ["prefetched.ogg"]

    async def fake_should_skip_deleted_user_job(
        user_id: int,
        job_created_at: float | None,
    ) -> bool:
        return False

    monkeypatch.setattr(prefetch_service, "generate_voice", fake_generate_voice)
    monkeypatch.setattr(
        prefetch_service.privacy_service,
        "should_skip_deleted_user_job",
        fake_should_skip_deleted_user_job,
    )

    await session_store.set_reading_session(
        user_id=7,
        session={
            "session_id": "session-1",
            "chunks": ["current", "next chunk"],
            "index": 0,
        },
    )

    await prefetch_service.run_prefetch_audio_job(
        PrefetchAudioJobCommand.from_serialized_job(
            audio_queue.build_prefetch_chunk_job(
                user_id=7,
                session_id="session-1",
                chunk_index=1,
                chunk_text="next chunk",
                voice="uk-UA-PolinaNeural",
                rate="+0%",
                provider_chain=["edge"],
                created_at=123.5,
            )
        )
    )

    session = await session_store.get_reading_session(7)

    assert session is not None
    assert session["prefetch_state"] == "ready"
    assert session["prefetch_index"] == 1
    assert session["prefetch_audio_files"] == ["prefetched.ogg"]
    assert session["prefetch_error"] == ""


@pytest.mark.asyncio
async def test_get_audio_from_prefetch_or_generate_consumes_ready_prefetch() -> None:
    await session_store.set_reading_session(
        user_id=8,
        session={
            "session_id": "session-1",
            "chunks": ["current"],
            "index": 0,
            "prefetch_state": "ready",
            "prefetch_index": 0,
            "prefetch_audio_files": ["ready.ogg"],
            "prefetch_error": "",
        },
    )
    session = await session_store.get_reading_session_model(8)
    status_msg = FakeStatusMessage()

    result = await prefetch_service.get_audio_from_prefetch_or_generate(
        ResolvePrefetchedAudioCommand(
            message=None,
            user_id=8,
            session=session,
            chunk_text="current",
            voice="uk-UA-PolinaNeural",
            rate="+0%",
            provider_chain=["edge"],
            current_part=1,
            total_parts=1,
            status_msg=status_msg,
        )
    )

    refreshed = await session_store.get_reading_session(8)

    assert result.audio_files == ["ready.ogg"]
    assert refreshed is not None
    assert refreshed["prefetch_state"] == "none"
    assert refreshed["prefetch_index"] == -1
    assert refreshed["prefetch_audio_files"] == []
    assert refreshed["prefetch_error"] == ""
    assert status_msg.deleted is True


@pytest.mark.asyncio
async def test_start_prefetch_next_chunk_enqueues_redis_job(monkeypatch) -> None:
    captured = {}

    async def fake_enqueue_redis_audio_job(job) -> None:
        captured.update(job)

    monkeypatch.setattr(
        prefetch_service,
        "select_voice_for_text",
        lambda text, voice_pref: "selected-voice",
    )
    monkeypatch.setattr(
        prefetch_service,
        "build_user_tts_provider_chain",
        lambda provider, voice: [provider, voice],
    )

    await session_store.set_reading_session(
        user_id=9,
        session={
            "session_id": "session-1",
            "chunks": ["current", "next"],
            "index": 0,
        },
    )

    await prefetch_service.start_prefetch_next_chunk(
        StartPrefetchCommand(
            user_id=9,
            session_id="session-1",
            chunks=["current", "next"],
            next_index=1,
            voice_pref="voice-pref",
            rate="+0%",
            tts_provider="edge",
        ),
        queue_orchestrator=ReadingAudioQueueOrchestrator(
            use_redis_audio_queue=lambda: True,
            redis_audio_queue_position=lambda: None,
            enqueue_redis_audio_job=fake_enqueue_redis_audio_job,
            memory_audio_queue_position=lambda: 0,
            enqueue_memory_audio_job=lambda job: None,
        ),
    )

    session = await session_store.get_reading_session(9)
    created_at = captured.pop("created_at")

    assert isinstance(created_at, float)
    assert captured == {
        "type": "prefetch_chunk",
        "user_id": 9,
        "session_id": "session-1",
        "chunk_index": 1,
        "chunk_text": "next",
        "voice": "selected-voice",
        "rate": "+0%",
        "provider_chain": ["edge", "selected-voice"],
    }
    assert session is not None
    assert session["prefetch_state"] == "queued"
    assert session["prefetch_index"] == 1
    assert session["prefetch_audio_files"] == []
    assert session["prefetch_error"] == ""


@pytest.mark.asyncio
async def test_start_prefetch_next_chunk_marks_failed_on_redis_capacity(
    monkeypatch,
) -> None:
    async def fake_enqueue_redis_audio_job(job) -> None:
        raise asyncio.QueueFull

    await session_store.set_reading_session(
        user_id=10,
        session={
            "session_id": "session-1",
            "chunks": ["current", "next"],
            "index": 0,
        },
    )

    await prefetch_service.start_prefetch_next_chunk(
        StartPrefetchCommand(
            user_id=10,
            session_id="session-1",
            chunks=["current", "next"],
            next_index=1,
            voice_pref="uk-UA-PolinaNeural",
            rate="+0%",
            tts_provider="edge",
        ),
        queue_orchestrator=ReadingAudioQueueOrchestrator(
            use_redis_audio_queue=lambda: True,
            redis_audio_queue_position=lambda: None,
            enqueue_redis_audio_job=fake_enqueue_redis_audio_job,
            memory_audio_queue_position=lambda: 0,
            enqueue_memory_audio_job=lambda job: None,
        ),
    )

    session = await session_store.get_reading_session(10)

    assert session is not None
    assert session["prefetch_state"] == "failed"
    assert session["prefetch_index"] == 1
    assert session["prefetch_audio_files"] == []
    assert session["prefetch_error"] == "queue_failed"
