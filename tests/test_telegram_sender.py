from types import SimpleNamespace

import pytest

from services import telegram_sender


class FakeBot:
    def __init__(self) -> None:
        self.calls = []

    async def send_voice(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message_id=1)


class FakeMessage:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(id=123)
        self.calls = []

    async def answer_voice(self, voice, **kwargs):
        self.calls.append({
            "voice": voice,
            **kwargs,
        })
        return SimpleNamespace(message_id=2)


@pytest.mark.asyncio
async def test_safe_send_voice_returns_sent_message(monkeypatch) -> None:
    delays = []

    async def fake_sleep_after_send(delay_seconds):
        delays.append(delay_seconds)

    monkeypatch.setattr(
        telegram_sender,
        "sleep_after_send",
        fake_sleep_after_send,
    )

    bot = FakeBot()

    result = await telegram_sender.safe_send_voice(
        bot=bot,
        chat_id=10,
        voice="file_id",
        caption="caption",
        delay_seconds=0.5,
    )

    assert result.message_id == 1
    assert bot.calls == [{
        "chat_id": 10,
        "voice": "file_id",
        "caption": "caption",
        "reply_markup": None,
    }]
    assert delays == [0.5]


@pytest.mark.asyncio
async def test_safe_answer_voice_returns_none_on_unexpected_error() -> None:
    class BrokenMessage:
        chat = SimpleNamespace(id=123)

        async def answer_voice(self, *args, **kwargs):
            raise RuntimeError("boom")

    result = await telegram_sender.safe_answer_voice(
        message=BrokenMessage(),
        voice="file",
    )

    assert result is None


@pytest.mark.asyncio
async def test_safe_answer_voice_passes_caption_and_markup() -> None:
    message = FakeMessage()
    markup = object()

    result = await telegram_sender.safe_answer_voice(
        message=message,
        voice="voice",
        caption="caption",
        reply_markup=markup,
    )

    assert result.message_id == 2
    assert message.calls == [{
        "voice": "voice",
        "caption": "caption",
        "reply_markup": markup,
    }]
