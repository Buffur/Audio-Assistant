from types import SimpleNamespace

import pytest

from handlers import callback_guards


class FakeCallback:
    def __init__(self, *, user_id=123, message=None, data="prefix:123") -> None:
        self.from_user = (
            SimpleNamespace(id=user_id)
            if user_id is not None
            else None
        )
        self.message = message
        self.data = data
        self.answers = []

    async def answer(self, text=None, show_alert=None, **kwargs) -> None:
        self.answers.append({
            "text": text,
            "show_alert": show_alert,
        })


def test_callback_user_id_and_message_user_id() -> None:
    assert callback_guards.callback_user_id(FakeCallback(user_id=456)) == 456
    assert callback_guards.callback_user_id(FakeCallback(user_id=None)) is None

    message = SimpleNamespace(from_user=SimpleNamespace(id=789))
    assert callback_guards.message_user_id(message) == 789


def test_callback_owner_matches_requires_sender() -> None:
    assert callback_guards.callback_owner_matches(FakeCallback(user_id=1), 1)
    assert not callback_guards.callback_owner_matches(FakeCallback(user_id=1), 2)
    assert not callback_guards.callback_owner_matches(FakeCallback(user_id=None), 1)


def test_parsed_callback_owner_matches() -> None:
    callback = FakeCallback(user_id=123, data="delete:123")

    assert callback_guards.parsed_callback_owner_matches(
        callback,
        lambda data: int(data.rsplit(":", 1)[1]),
    )


@pytest.mark.asyncio
async def test_require_callback_message_alerts_when_missing() -> None:
    callback = FakeCallback(message=None)

    result = await callback_guards.require_callback_message(callback)

    assert result is None
    assert callback.answers == [{
        "text": callback_guards.CALLBACK_MESSAGE_MISSING_TEXT,
        "show_alert": True,
    }]
