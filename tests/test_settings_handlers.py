from types import SimpleNamespace

import pytest

from handlers import settings
from keyboards.settings import (
    SETTINGS_PREVIEW_CALLBACK,
    SPEED_PLUS_25_CALLBACK,
    VOICE_FEMALE_CALLBACK,
)


class FakeSettingsMessage:
    def __init__(self) -> None:
        self.edits = []

    async def edit_text(self, text: str, **kwargs) -> None:
        self.edits.append({
            "text": text,
            **kwargs,
        })


class FakeSettingsCallback:
    def __init__(self, data: str) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=1)
        self.message = FakeSettingsMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=None, **kwargs) -> None:
        self.answers.append({
            "text": text,
            "show_alert": show_alert,
        })


@pytest.mark.asyncio
async def test_change_voice_updates_settings_without_auto_preview(monkeypatch) -> None:
    captured = {}

    async def fake_update_user_voice(**kwargs) -> None:
        captured["updated_voice"] = kwargs

    async def fake_get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+0%"

    async def fail_generate_voice(*args, **kwargs):
        raise AssertionError("changing voice should not auto-generate preview")

    monkeypatch.setattr(settings, "update_user_voice", fake_update_user_voice)
    monkeypatch.setattr(
        settings,
        "get_effective_user_settings",
        fake_get_effective_user_settings,
    )
    monkeypatch.setattr(settings, "generate_voice", fail_generate_voice)

    callback = FakeSettingsCallback(VOICE_FEMALE_CALLBACK)

    await settings.change_voice(callback)

    assert captured["updated_voice"] == {
        "user_id": 1,
        "voice": "uk-UA-PolinaNeural",
    }
    assert callback.answers == [
        {
            "text": settings.FEMALE_VOICE_CONFIRM_TEXT,
            "show_alert": None,
        }
    ]
    assert callback.message.edits


@pytest.mark.asyncio
async def test_change_speed_updates_settings_without_auto_preview(monkeypatch) -> None:
    captured = {}

    async def fake_update_user_rate(**kwargs) -> None:
        captured["updated_rate"] = kwargs

    async def fake_get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+25%"

    async def fail_generate_voice(*args, **kwargs):
        raise AssertionError("changing speed should not auto-generate preview")

    monkeypatch.setattr(settings, "update_user_rate", fake_update_user_rate)
    monkeypatch.setattr(
        settings,
        "get_effective_user_settings",
        fake_get_effective_user_settings,
    )
    monkeypatch.setattr(settings, "generate_voice", fail_generate_voice)

    callback = FakeSettingsCallback(SPEED_PLUS_25_CALLBACK)

    await settings.change_speed(callback)

    assert captured["updated_rate"] == {
        "user_id": 1,
        "rate": "+25%",
    }
    assert callback.answers == [
        {
            "text": "Швидкість читання встановлено на 1.25x",
            "show_alert": None,
        }
    ]
    assert callback.message.edits


@pytest.mark.asyncio
async def test_settings_preview_sends_voice_example(monkeypatch) -> None:
    captured = {}

    async def fake_get_effective_user_settings(user_id: int):
        return "uk-UA-PolinaNeural", "+0%"

    async def fake_get_effective_user_tts_provider(user_id: int) -> str:
        return "edge"

    async def fake_send_voice_preview(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        settings,
        "get_effective_user_settings",
        fake_get_effective_user_settings,
    )
    monkeypatch.setattr(
        settings,
        "get_effective_user_tts_provider",
        fake_get_effective_user_tts_provider,
    )
    monkeypatch.setattr(settings, "_send_voice_preview", fake_send_voice_preview)

    callback = FakeSettingsCallback(SETTINGS_PREVIEW_CALLBACK)

    await settings.settings_preview(callback)

    assert callback.answers == [
        {
            "text": settings.SETTINGS_PREVIEW_PREPARING_TEXT,
            "show_alert": None,
        }
    ]
    assert captured["text"] == settings.SETTINGS_PREVIEW_TEXT
    assert captured["voice"] == "uk-UA-PolinaNeural"
    assert captured["rate"] == "+0%"
    assert captured["tts_provider"] == "edge"
