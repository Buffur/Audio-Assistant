from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramEntityTooLarge, TelegramNetworkError

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


@pytest.mark.asyncio
async def test_send_with_retry_retries_transient_network_error(monkeypatch) -> None:
    calls = 0
    delays = []

    async def fake_sleep(delay_seconds):
        delays.append(delay_seconds)

    async def operation():
        nonlocal calls
        calls += 1

        if calls == 1:
            raise TelegramNetworkError(
                method=SimpleNamespace(),
                message="temporary network failure",
            )

        return "ok"

    monkeypatch.setattr(telegram_sender.asyncio, "sleep", fake_sleep)

    result = await telegram_sender._send_with_retry(
        operation,
        context="test",
        retry_attempts=2,
    )

    assert result == "ok"
    assert calls == 2
    assert delays == [telegram_sender.DEFAULT_RETRY_BASE_DELAY_SECONDS]


@pytest.mark.asyncio
async def test_send_with_retry_does_not_retry_entity_too_large(monkeypatch) -> None:
    calls = 0
    delays = []

    async def fake_sleep(delay_seconds):
        delays.append(delay_seconds)

    async def operation():
        nonlocal calls
        calls += 1
        raise TelegramEntityTooLarge(
            method=SimpleNamespace(),
            message="payload is too large",
        )

    monkeypatch.setattr(telegram_sender.asyncio, "sleep", fake_sleep)

    result = await telegram_sender._send_with_retry(
        operation,
        context="test",
        retry_attempts=3,
    )

    assert result is None
    assert calls == 1
    assert delays == []
