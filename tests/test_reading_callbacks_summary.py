import pytest
import pytest_asyncio

from handlers import reading_callbacks
from keyboards.reading import (
    READ_NEXT_ACTION,
    READ_SUMMARY_ACTION,
    build_reading_callback,
)
from services import reading_session_store as store
from texts.limits import SUMMARY_LIMIT_REACHED_TEXT
from texts.messages import (
    OUTDATED_READING_BUTTON_TEXT,
    SESSION_NOT_FOUND_TEXT,
    SUMMARY_ALREADY_READY_TEXT,
    SUMMARY_ALREADY_SENT_TEXT,
)


class FakeStatusMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.status_messages: list[FakeStatusMessage] = []
        self.reply_markup_edits = []

    async def answer(self, text: str, **kwargs):
        self.answers.append(text)
        status = FakeStatusMessage(text)
        self.status_messages.append(status)
        return status

    async def edit_reply_markup(self, reply_markup=None) -> None:
        self.reply_markup_edits.append(reply_markup)


class FakeCallback:
    def __init__(
        self,
        user_id: int = 1,
        session_id: str = "session-1",
        action: str = READ_SUMMARY_ACTION,
    ) -> None:
        self.from_user = type("FakeUser", (), {"id": user_id})()
        self.data = build_reading_callback(action, session_id)
        self.message = FakeMessage()
        self.answers: list[dict[str, object]] = []

    async def answer(self, text=None, show_alert=None, **kwargs) -> None:
        self.answers.append({
            "text": text,
            "show_alert": show_alert,
        })


@pytest_asyncio.fixture(autouse=True)
async def cleanup_reading_sessions():
    await store.cleanup_all_reading_sessions()
    yield
    await store.cleanup_all_reading_sessions()


@pytest.mark.asyncio
async def test_reading_callback_context_reports_missing_session() -> None:
    callback = FakeCallback()

    result = await reading_callbacks._get_reading_callback_context(
        callback,
        missing_text=SESSION_NOT_FOUND_TEXT,
    )

    assert result is None
    assert callback.answers == [{
        "text": SESSION_NOT_FOUND_TEXT,
        "show_alert": True,
    }]


@pytest.mark.asyncio
async def test_reading_callback_context_rejects_outdated_session() -> None:
    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-current",
            "chunks": ["part 1"],
            "index": 0,
        },
    )
    callback = FakeCallback(session_id="session-old")

    result = await reading_callbacks._get_reading_callback_context(
        callback,
        missing_text=SESSION_NOT_FOUND_TEXT,
    )

    assert result is None
    assert callback.answers == [{
        "text": OUTDATED_READING_BUTTON_TEXT,
        "show_alert": True,
    }]


@pytest.mark.asyncio
async def test_read_summary_generates_once_and_caches_summary(monkeypatch) -> None:
    captured = {}

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["part 1", "part 2"],
            "index": 0,
            "is_generating": False,
            "catalog_document_id": 42,
        },
    )

    async def fake_reserve_summary_generation(user_id: int) -> bool:
        captured["reserved_for"] = user_id
        return True

    async def fake_summarize_text_with_ai(text: str) -> str:
        captured["summarized_text"] = text
        return "cached summary"

    async def fake_get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+0%"

    async def fake_get_effective_user_tts_provider(user_id: int) -> str:
        return "edge"

    async def fake_is_premium_user(user_id: int) -> bool:
        return False

    async def fake_generate_voice(**kwargs):
        captured["voice_text"] = kwargs["text"]
        return ["summary.ogg"]

    async def fake_send_voice_files(**kwargs) -> None:
        captured["sent_caption"] = kwargs["caption"]
        captured["sent_reply_markup"] = kwargs["reply_markup"]
        return ["summary-file-id"]

    async def fake_save_catalog_document_summary(**kwargs) -> bool:
        captured["catalog_summary"] = kwargs
        return True

    async def fake_save_catalog_document_summary_audio(**kwargs) -> bool:
        captured["catalog_summary_audio"] = kwargs
        return True

    monkeypatch.setattr(
        reading_callbacks,
        "reserve_summary_generation",
        fake_reserve_summary_generation,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "summarize_text_with_ai",
        fake_summarize_text_with_ai,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "get_effective_user_settings",
        fake_get_effective_user_settings,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "get_effective_user_tts_provider",
        fake_get_effective_user_tts_provider,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "is_premium_user",
        fake_is_premium_user,
    )
    monkeypatch.setattr(reading_callbacks, "generate_voice", fake_generate_voice)
    monkeypatch.setattr(
        reading_callbacks,
        "send_voice_files",
        fake_send_voice_files,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "save_catalog_document_summary",
        fake_save_catalog_document_summary,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "save_catalog_document_summary_audio",
        fake_save_catalog_document_summary_audio,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "select_voice_for_text",
        lambda text, voice_pref: "uk-UA-PolinaNeural",
    )

    callback = FakeCallback()

    await reading_callbacks.process_read_summary(callback)

    session = await store.get_reading_session(1)

    assert captured["reserved_for"] == 1
    assert captured["summarized_text"] == "part 1\n\npart 2"
    assert captured["voice_text"] == "cached summary"
    assert captured["catalog_summary"] == {
        "user_id": 1,
        "document_id": 42,
        "summary_text": "cached summary",
    }
    assert captured["catalog_summary_audio"] == {
        "user_id": 1,
        "document_id": 42,
        "voice_file_ids": ["summary-file-id"],
        "voice": "uk-UA-PolinaNeural",
        "rate": "+0%",
        "provider": "edge",
    }
    assert session["summary_text"] == "cached summary"
    assert session["summary_delivered"] is True
    assert session["summary_voice_file_ids"] == ["summary-file-id"]
    assert session["is_generating"] is False
    assert callback.message.reply_markup_edits == [None]


@pytest.mark.asyncio
async def test_read_summary_uses_cached_text_for_tts_without_ai_or_quota(
    monkeypatch,
) -> None:
    captured = {}

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["part 1", "part 2"],
            "index": 0,
            "is_generating": False,
            "summary_text": "cached summary",
        },
    )

    async def fail_async(*args, **kwargs):
        raise AssertionError("cached summary path must not regenerate work")

    monkeypatch.setattr(reading_callbacks, "reserve_summary_generation", fail_async)
    monkeypatch.setattr(reading_callbacks, "summarize_text_with_ai", fail_async)

    async def fake_get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+0%"

    async def fake_get_effective_user_tts_provider(user_id: int) -> str:
        return "edge"

    async def fake_generate_voice(**kwargs):
        captured["voice_text"] = kwargs["text"]
        return ["summary.ogg"]

    async def fake_send_voice_files(**kwargs):
        captured["sent_caption"] = kwargs["caption"]
        return ["cached-summary-file-id"]

    monkeypatch.setattr(
        reading_callbacks,
        "get_effective_user_settings",
        fake_get_effective_user_settings,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "get_effective_user_tts_provider",
        fake_get_effective_user_tts_provider,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "select_voice_for_text",
        lambda text, voice_pref: "uk-UA-PolinaNeural",
    )
    monkeypatch.setattr(reading_callbacks, "generate_voice", fake_generate_voice)
    monkeypatch.setattr(reading_callbacks, "send_voice_files", fake_send_voice_files)

    callback = FakeCallback()

    await reading_callbacks.process_read_summary(callback)

    assert callback.answers == [
        {
            "text": SUMMARY_ALREADY_READY_TEXT,
            "show_alert": None,
        }
    ]
    assert callback.message.reply_markup_edits == [None]
    assert captured["voice_text"] == "cached summary"
    assert captured["sent_caption"] == reading_callbacks.SUMMARY_CAPTION_TEXT
    session = await store.get_reading_session(1)
    assert session["summary_voice_file_ids"] == ["cached-summary-file-id"]


@pytest.mark.asyncio
async def test_read_summary_reuses_cached_voice_file_id(monkeypatch) -> None:
    captured = {}

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["part 1", "part 2"],
            "index": 0,
            "is_generating": False,
            "summary_text": "cached summary",
            "summary_voice_file_ids": ["telegram-file-id"],
            "summary_voice_voice": "uk-UA-PolinaNeural",
            "summary_voice_rate": "+0%",
            "summary_voice_provider": "edge",
        },
    )

    async def fail_async(*args, **kwargs):
        raise AssertionError("cached voice path must not regenerate work")

    async def fake_get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+0%"

    async def fake_get_effective_user_tts_provider(user_id: int) -> str:
        return "edge"

    async def fake_send_voice_file_ids(**kwargs):
        captured["voice_file_ids"] = kwargs["voice_file_ids"]
        captured["caption"] = kwargs["caption"]
        return ["telegram-file-id"]

    monkeypatch.setattr(reading_callbacks, "reserve_summary_generation", fail_async)
    monkeypatch.setattr(reading_callbacks, "summarize_text_with_ai", fail_async)
    monkeypatch.setattr(reading_callbacks, "generate_voice", fail_async)
    monkeypatch.setattr(
        reading_callbacks,
        "get_effective_user_settings",
        fake_get_effective_user_settings,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "get_effective_user_tts_provider",
        fake_get_effective_user_tts_provider,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "select_voice_for_text",
        lambda text, voice_pref: "uk-UA-PolinaNeural",
    )
    monkeypatch.setattr(
        reading_callbacks,
        "send_voice_file_ids",
        fake_send_voice_file_ids,
    )

    callback = FakeCallback()

    await reading_callbacks.process_read_summary(callback)

    assert captured["voice_file_ids"] == ["telegram-file-id"]
    assert captured["caption"] == reading_callbacks.SUMMARY_CAPTION_TEXT
    assert callback.answers == [
        {
            "text": SUMMARY_ALREADY_READY_TEXT,
            "show_alert": None,
        }
    ]


@pytest.mark.asyncio
async def test_read_summary_does_not_duplicate_already_delivered_summary(
    monkeypatch,
) -> None:
    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["part 1", "part 2"],
            "index": 0,
            "is_generating": False,
            "summary_text": "cached summary",
            "summary_delivered": True,
        },
    )

    async def fail_async(*args, **kwargs):
        raise AssertionError("delivered summary must not regenerate work")

    monkeypatch.setattr(reading_callbacks, "try_start_generation", fail_async)
    monkeypatch.setattr(reading_callbacks, "reserve_summary_generation", fail_async)
    monkeypatch.setattr(reading_callbacks, "summarize_text_with_ai", fail_async)
    monkeypatch.setattr(reading_callbacks, "generate_voice", fail_async)

    callback = FakeCallback()

    await reading_callbacks.process_read_summary(callback)

    assert callback.answers == [
        {
            "text": SUMMARY_ALREADY_SENT_TEXT,
            "show_alert": True,
        }
    ]
    assert callback.message.reply_markup_edits == [None]
    assert callback.message.answers == []


@pytest.mark.asyncio
async def test_read_summary_limit_rejection_releases_generation_flag(
    monkeypatch,
) -> None:
    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["part 1", "part 2"],
            "index": 0,
            "is_generating": False,
        },
    )

    async def fake_reserve_summary_generation(user_id: int) -> bool:
        return False

    async def fail_async(*args, **kwargs):
        raise AssertionError("summary limit rejection must stop before AI/TTS")

    monkeypatch.setattr(
        reading_callbacks,
        "reserve_summary_generation",
        fake_reserve_summary_generation,
    )
    monkeypatch.setattr(reading_callbacks, "summarize_text_with_ai", fail_async)
    monkeypatch.setattr(reading_callbacks, "generate_voice", fail_async)

    callback = FakeCallback()

    await reading_callbacks.process_read_summary(callback)

    session = await store.get_reading_session(1)

    assert callback.answers == [
        {
            "text": SUMMARY_LIMIT_REACHED_TEXT,
            "show_alert": True,
        }
    ]
    assert session["is_generating"] is False
    assert "summary_text" not in session


@pytest.mark.asyncio
async def test_read_summary_refunds_limit_when_ai_returns_error(monkeypatch) -> None:
    captured = {}

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["part 1", "part 2"],
            "index": 0,
            "is_generating": False,
        },
    )

    async def fake_reserve_summary_generation(user_id: int) -> bool:
        captured["reserved_for"] = user_id
        return True

    async def fake_refund_summary_generation(user_id: int) -> None:
        captured["refunded_for"] = user_id

    async def fake_summarize_text_with_ai(text: str) -> str:
        return reading_callbacks.SUMMARY_GENERATION_ERROR

    async def fail_async(*args, **kwargs):
        raise AssertionError("AI error must stop before TTS")

    monkeypatch.setattr(
        reading_callbacks,
        "reserve_summary_generation",
        fake_reserve_summary_generation,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "refund_summary_generation",
        fake_refund_summary_generation,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "summarize_text_with_ai",
        fake_summarize_text_with_ai,
    )
    monkeypatch.setattr(reading_callbacks, "generate_voice", fail_async)

    callback = FakeCallback()

    await reading_callbacks.process_read_summary(callback)

    session = await store.get_reading_session(1)

    assert captured == {
        "reserved_for": 1,
        "refunded_for": 1,
    }
    assert callback.message.answers == [
        reading_callbacks.SUMMARY_PREPARING_TEXT,
        reading_callbacks.SUMMARY_GENERATION_ERROR,
    ]
    assert session["is_generating"] is False
    assert "summary_text" not in session


@pytest.mark.asyncio
async def test_read_summary_refunds_limit_when_tts_fails(monkeypatch) -> None:
    captured = {}

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["part 1", "part 2"],
            "index": 0,
            "is_generating": False,
        },
    )

    async def fake_reserve_summary_generation(user_id: int) -> bool:
        captured["reserved_for"] = user_id
        return True

    async def fake_refund_summary_generation(user_id: int) -> None:
        captured["refunded_for"] = user_id

    async def fake_summarize_text_with_ai(text: str) -> str:
        return "summary text"

    async def fake_get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+0%"

    async def fake_get_effective_user_tts_provider(user_id: int) -> str:
        return "edge"

    async def fake_generate_voice(**kwargs):
        return []

    monkeypatch.setattr(
        reading_callbacks,
        "reserve_summary_generation",
        fake_reserve_summary_generation,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "refund_summary_generation",
        fake_refund_summary_generation,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "summarize_text_with_ai",
        fake_summarize_text_with_ai,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "get_effective_user_settings",
        fake_get_effective_user_settings,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "get_effective_user_tts_provider",
        fake_get_effective_user_tts_provider,
    )
    monkeypatch.setattr(
        reading_callbacks,
        "select_voice_for_text",
        lambda text, voice_pref: "uk-UA-PolinaNeural",
    )
    monkeypatch.setattr(reading_callbacks, "generate_voice", fake_generate_voice)

    callback = FakeCallback()

    await reading_callbacks.process_read_summary(callback)

    session = await store.get_reading_session(1)

    assert captured == {
        "reserved_for": 1,
        "refunded_for": 1,
    }
    assert callback.message.answers == [
        reading_callbacks.SUMMARY_PREPARING_TEXT,
        reading_callbacks.SUMMARY_AUDIO_GENERATION_ERROR,
    ]
    assert session["is_generating"] is False
    assert "summary_text" not in session


@pytest.mark.asyncio
async def test_read_next_keeps_summary_button_until_cached_summary_is_shown(
    monkeypatch,
) -> None:
    captured = {}

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "session-1",
            "chunks": ["part 1", "part 2"],
            "index": 0,
            "is_generating": False,
            "summary_text": "cached summary",
            "summary_delivered": False,
        },
    )

    async def fake_is_premium_user(user_id: int) -> bool:
        return False

    async def fake_send_audio_chunk(message, user_id) -> None:
        captured["sent"] = True

    monkeypatch.setattr(reading_callbacks, "is_premium_user", fake_is_premium_user)
    monkeypatch.setattr(reading_callbacks, "send_audio_chunk", fake_send_audio_chunk)

    callback = FakeCallback(action=READ_NEXT_ACTION)

    await reading_callbacks.process_read_next(callback)

    callbacks = [
        button.callback_data
        for row in callback.message.reply_markup_edits[0].inline_keyboard
        for button in row
    ]

    assert captured["sent"] is True
    assert any(
        callback_data.startswith(READ_SUMMARY_ACTION)
        for callback_data in callbacks
    )
