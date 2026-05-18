import pytest

from handlers import messages


class FakeStatusMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class FakeMessage:
    def __init__(self) -> None:
        self.text = "article"
        self.photo = None
        self.document = None
        self.answers: list[str] = []
        self.status_messages: list[FakeStatusMessage] = []

    async def answer(self, text: str, **kwargs):
        self.answers.append(text)
        status = FakeStatusMessage(text)
        self.status_messages.append(status)
        return status


@pytest.mark.asyncio
async def test_large_text_split_notice_is_not_voiced(monkeypatch) -> None:
    message = FakeMessage()
    captured = {}

    async def fake_reply_with_voice(*args, **kwargs):
        raise AssertionError("large split notice must not use TTS")

    async def fake_cleanup_session(user_id):
        captured["cleanup_user_id"] = user_id

    async def fake_extract_text_from_message(**kwargs):
        return "large article"

    async def fake_reserve_input_processing(user_id, usage_type):
        return True

    async def fake_save_document_history_from_message(**kwargs):
        captured["history"] = kwargs

    async def fake_set_reading_session(**kwargs):
        captured["session"] = kwargs

    async def fake_send_audio_chunk(message_arg, user_id):
        captured["send_audio"] = {
            "message": message_arg,
            "user_id": user_id,
        }

    monkeypatch.setattr(messages, "cleanup_session", fake_cleanup_session)
    monkeypatch.setattr(
        messages,
        "reserve_input_processing",
        fake_reserve_input_processing,
    )
    monkeypatch.setattr(
        messages,
        "extract_text_from_message",
        fake_extract_text_from_message,
    )
    monkeypatch.setattr(messages, "split_text", lambda text: ["part 1", "part 2"])
    monkeypatch.setattr(
        messages,
        "save_document_history_from_message",
        fake_save_document_history_from_message,
    )
    monkeypatch.setattr(messages, "set_reading_session", fake_set_reading_session)
    monkeypatch.setattr(messages, "send_audio_chunk", fake_send_audio_chunk)
    monkeypatch.setattr(messages, "reply_with_voice", fake_reply_with_voice)

    await messages._process_message(message, user_id=123)

    assert message.answers == [
        messages.ANALYZING_MATERIAL_TEXT,
        messages.build_large_text_split_text(2),
    ]
    assert message.status_messages[0].deleted is True
    assert captured["session"]["user_id"] == 123
    assert captured["send_audio"] == {
        "message": message,
        "user_id": 123,
    }


@pytest.mark.asyncio
async def test_unsupported_document_format_error_is_text_only(monkeypatch) -> None:
    message = FakeMessage()

    async def fake_reply_with_voice(*args, **kwargs):
        raise AssertionError("unsupported format error must not use TTS")

    async def fake_extract_text_from_message(**kwargs):
        return messages.SUPPORTED_FORMATS_ERROR

    async def fake_reserve_input_processing(user_id, usage_type):
        return True

    monkeypatch.setattr(
        messages,
        "reserve_input_processing",
        fake_reserve_input_processing,
    )
    monkeypatch.setattr(
        messages,
        "extract_text_from_message",
        fake_extract_text_from_message,
    )
    monkeypatch.setattr(messages, "reply_with_voice", fake_reply_with_voice)

    async def fake_cleanup_session(user_id):
        return None

    monkeypatch.setattr(messages, "cleanup_session", fake_cleanup_session)

    await messages._process_message(message, user_id=123)

    assert message.answers == [
        messages.ANALYZING_MATERIAL_TEXT,
        messages.SUPPORTED_FORMATS_ERROR,
    ]
    assert message.status_messages[0].deleted is True


@pytest.mark.asyncio
async def test_new_material_is_rejected_while_audio_generation_is_active(
    monkeypatch,
) -> None:
    message = FakeMessage()

    async def fake_get_reading_session(user_id):
        return {
            "session_id": "active-session",
            "is_generating": True,
        }

    async def fail_cleanup_session(user_id):
        raise AssertionError("active generation must not be cleaned up")

    async def fail_reserve_input_processing(user_id, usage_type):
        raise AssertionError("quota must not be reserved for rejected material")

    monkeypatch.setattr(messages, "get_reading_session", fake_get_reading_session)
    monkeypatch.setattr(messages, "cleanup_session", fail_cleanup_session)
    monkeypatch.setattr(
        messages,
        "reserve_input_processing",
        fail_reserve_input_processing,
    )

    await messages._process_message(message, user_id=123)

    assert message.answers == [messages.WAIT_CURRENT_AUDIO_REQUEST_TEXT]
