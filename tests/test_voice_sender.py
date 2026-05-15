from types import SimpleNamespace

import pytest

from services import voice_sender


class FakeMessage:
    pass


@pytest.mark.asyncio
async def test_send_voice_files_can_caption_each_audio_file(monkeypatch) -> None:
    calls = []
    removed_files = []
    markup = object()

    async def fake_safe_answer_voice(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(message_id=len(calls))

    monkeypatch.setattr(voice_sender, "safe_answer_voice", fake_safe_answer_voice)
    monkeypatch.setattr(voice_sender, "safe_remove_file", removed_files.append)

    await voice_sender.send_voice_files(
        message=FakeMessage(),
        audio_files=["one.ogg", "two.ogg"],
        caption="base caption",
        reply_markup=markup,
        caption_builder=lambda index, total, caption: (
            f"{caption} · аудіо {index} з {total}"
        ),
    )

    assert [call["caption"] for call in calls] == [
        "base caption · аудіо 1 з 2",
        "base caption · аудіо 2 з 2",
    ]
    assert calls[0]["reply_markup"] is None
    assert calls[1]["reply_markup"] is markup
    assert removed_files == ["one.ogg", "two.ogg"]
