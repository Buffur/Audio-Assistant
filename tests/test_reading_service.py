import pytest
import pytest_asyncio

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
        self.status_messages: list[FakeStatusMessage] = []
        self.chat = type("FakeChat", (), {"id": 1001})()

    async def answer(self, text: str, **kwargs):
        self.answers.append(text)
        status = FakeStatusMessage(text)
        self.status_messages.append(status)
        return status


@pytest_asyncio.fixture(autouse=True)
async def cleanup_reading_state():
    await reading_service.close_reading_audio_queue(timeout_seconds=0.1)
    await store.cleanup_all_reading_sessions()
    yield
    await reading_service.close_reading_audio_queue(timeout_seconds=0.1)
    await store.cleanup_all_reading_sessions()


@pytest.mark.asyncio
async def test_send_audio_chunk_enqueues_background_job(monkeypatch) -> None:
    captured = {}

    async def fake_send_audio_chunk_now(
        message,
        user_id,
        expected_session_id,
        status_msg,
    ) -> None:
        captured.update(
            {
                "message": message,
                "user_id": user_id,
                "expected_session_id": expected_session_id,
                "status_msg": status_msg,
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

    assert captured == {
        "type": "send_chunk",
        "user_id": 1,
        "chat_id": 1001,
        "session_id": "session-redis",
        "status_message_id": 42,
    }
    assert "7" in message.answers[0]


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
    ) -> None:
        captured.update(
            {
                "message": message,
                "user_id": user_id,
                "expected_session_id": expected_session_id,
                "status_msg": status_msg,
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
    assert message.answers
