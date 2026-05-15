import pytest
import pytest_asyncio

from services import reading_service
from services import reading_session_store as store


class FakeStatusMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.edits: list[str] = []
        self.deleted = False

    async def edit_text(self, text: str) -> None:
        self.edits.append(text)
        self.text = text

    async def delete(self) -> None:
        self.deleted = True


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.status_messages: list[FakeStatusMessage] = []

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
