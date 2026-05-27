from types import SimpleNamespace

import pytest

from handlers import privacy
from keyboards.privacy import build_delete_my_data_confirm_callback


class FakeMessage:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(type="private")
        self.edits: list[dict[str, object]] = []

    async def edit_text(self, text: str, **kwargs) -> None:
        self.edits.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.data = build_delete_my_data_confirm_callback(user_id)
        self.message = FakeMessage()
        self.answers: list[dict[str, object]] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answers.append({"text": text, **kwargs})


@pytest.mark.asyncio
async def test_delete_my_data_invalidates_user_activity_cache(monkeypatch) -> None:
    captured = {}

    async def fake_cleanup_user_private_runtime_data(user_id: int) -> dict[str, int]:
        captured["runtime_user_id"] = user_id
        return {
            "reading_session": 0,
            "queued_audio_jobs": 0,
        }

    async def fake_delete_user_private_data(user_id: int) -> dict[str, int]:
        captured["db_user_id"] = user_id
        return {
            "document_history": 0,
            "user_settings": 1,
        }

    def fake_invalidate_user_activity_cache(user_id: int) -> None:
        captured["invalidated_user_id"] = user_id

    monkeypatch.setattr(
        privacy,
        "cleanup_user_private_runtime_data",
        fake_cleanup_user_private_runtime_data,
    )
    monkeypatch.setattr(
        privacy,
        "delete_user_private_data",
        fake_delete_user_private_data,
    )
    monkeypatch.setattr(
        privacy,
        "invalidate_user_activity_cache",
        fake_invalidate_user_activity_cache,
    )

    callback = FakeCallback(user_id=123)

    await privacy.delete_my_data_confirm_callback(callback)

    assert captured == {
        "runtime_user_id": 123,
        "db_user_id": 123,
        "invalidated_user_id": 123,
    }
    assert callback.message.edits
    rendered_text = str(callback.message.edits[0]["text"])
    assert "Файли кешу озвучки" not in rendered_text
    assert "Денні лічильники" not in rendered_text
    assert "Історія документів:" not in rendered_text
    assert callback.answers
