import asyncio

import pytest

from handlers import catalog
from keyboards.catalog import CATALOG_OPEN_PREFIX
from texts.catalog import (
    CATALOG_DOCUMENT_ALREADY_OPEN_TEXT,
    CATALOG_OPEN_BUSY_TEXT,
)


class FakeStatusMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class FakeMessage:
    def __init__(self) -> None:
        self.chat = type("FakeChat", (), {"type": "private"})()
        self.answers: list[str] = []
        self.answer_kwargs: list[dict] = []
        self.status_messages: list[FakeStatusMessage] = []

    async def answer(self, text: str, **kwargs):
        self.answers.append(text)
        self.answer_kwargs.append(kwargs)
        status = FakeStatusMessage(text)
        self.status_messages.append(status)
        return status


class FakeCallback:
    def __init__(self, document_id: int = 42) -> None:
        self.from_user = type("FakeUser", (), {"id": 1})()
        self.message = FakeMessage()
        self.data = f"{CATALOG_OPEN_PREFIX}{document_id}"
        self.answers: list[dict[str, object]] = []

    async def answer(self, text=None, show_alert=None, **kwargs) -> None:
        self.answers.append({
            "text": text,
            "show_alert": show_alert,
        })


@pytest.fixture(autouse=True)
def cleanup_catalog_open_locks():
    catalog._catalog_open_locks.clear()
    catalog._catalog_open_lock_usage.clear()
    yield
    catalog._catalog_open_locks.clear()
    catalog._catalog_open_lock_usage.clear()


@pytest.mark.asyncio
async def test_catalog_open_spam_does_not_enqueue_duplicate_audio(monkeypatch) -> None:
    state = {"session": None}
    captured = {
        "history_reads": 0,
        "start_calls": 0,
        "send_calls": 0,
    }

    async def fake_get_current_reading_session(user_id: int):
        return state["session"]

    async def fake_get_catalog_document_chunks(user_id: int, document_id: int):
        captured["history_reads"] += 1
        return (
            {
                "id": document_id,
                "source_name": "Document",
                "summary_text": None,
                "summary_voice_file_ids_json": None,
                "summary_voice_voice": None,
                "summary_voice_rate": None,
                "summary_voice_provider": None,
            },
            ["part 1", "part 2"],
        )

    async def fake_start_reading_session(**kwargs):
        captured["start_calls"] += 1
        await asyncio.sleep(0.01)
        state["session"] = {
            "catalog_document_id": kwargs["catalog_document_id"],
            "is_generating": True,
        }

    async def fake_send_audio_chunk(message, user_id: int) -> None:
        captured["send_calls"] += 1

    monkeypatch.setattr(
        catalog,
        "get_current_reading_session",
        fake_get_current_reading_session,
    )
    monkeypatch.setattr(
        catalog,
        "get_catalog_document_chunks",
        fake_get_catalog_document_chunks,
    )
    monkeypatch.setattr(catalog, "start_reading_session", fake_start_reading_session)
    monkeypatch.setattr(catalog, "send_audio_chunk", fake_send_audio_chunk)

    first_callback = FakeCallback(document_id=42)
    second_callback = FakeCallback(document_id=42)

    await asyncio.gather(
        catalog.open_catalog_document(first_callback),
        catalog.open_catalog_document(second_callback),
    )

    all_callback_answers = first_callback.answers + second_callback.answers

    assert captured == {
        "history_reads": 1,
        "start_calls": 1,
        "send_calls": 1,
    }
    assert {
        "text": CATALOG_DOCUMENT_ALREADY_OPEN_TEXT,
        "show_alert": True,
    } in all_callback_answers


@pytest.mark.asyncio
async def test_catalog_open_rejects_while_another_document_is_generating(
    monkeypatch,
) -> None:
    async def fake_get_current_reading_session(user_id: int):
        return {
            "catalog_document_id": 99,
            "is_generating": True,
        }

    async def fail_get_catalog_document_chunks(user_id: int, document_id: int):
        raise AssertionError("busy catalog open must not read document chunks")

    async def fail_start_reading_session(**kwargs):
        raise AssertionError("busy catalog open must not start a new session")

    async def fail_send_audio_chunk(message, user_id: int) -> None:
        raise AssertionError("busy catalog open must not enqueue audio")

    monkeypatch.setattr(
        catalog,
        "get_current_reading_session",
        fake_get_current_reading_session,
    )
    monkeypatch.setattr(
        catalog,
        "get_catalog_document_chunks",
        fail_get_catalog_document_chunks,
    )
    monkeypatch.setattr(catalog, "start_reading_session", fail_start_reading_session)
    monkeypatch.setattr(catalog, "send_audio_chunk", fail_send_audio_chunk)

    callback = FakeCallback(document_id=42)

    await catalog.open_catalog_document(callback)

    assert callback.answers == [{
        "text": CATALOG_OPEN_BUSY_TEXT,
        "show_alert": True,
    }]
