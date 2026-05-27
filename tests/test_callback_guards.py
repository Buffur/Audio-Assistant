from types import SimpleNamespace

import pytest

from handlers import callback_guards


class FakeMessage:
    def __init__(self, *, user_id=123, chat_type="private") -> None:
        self.from_user = (
            SimpleNamespace(id=user_id)
            if user_id is not None
            else None
        )
        self.chat = SimpleNamespace(type=chat_type)
        self.answers = []

    async def answer(self, text=None, **kwargs) -> None:
        self.answers.append({
            "text": text,
            **kwargs,
        })


class FakeCallback:
    def __init__(
        self,
        *,
        user_id=123,
        message=None,
        data="prefix:123",
    ) -> None:
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

    message = FakeMessage(user_id=789)
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


@pytest.mark.asyncio
async def test_require_private_message_user_rejects_non_private_chat() -> None:
    message = FakeMessage(user_id=1, chat_type="group")

    result = await callback_guards.require_private_message_user(message)

    assert result is None
    assert message.answers == [{
        "text": callback_guards.PRIVATE_CHAT_REQUIRED_TEXT,
    }]


@pytest.mark.asyncio
async def test_require_private_callback_user_rejects_missing_user() -> None:
    callback = FakeCallback(
        user_id=None,
        message=FakeMessage(chat_type="private"),
    )

    result = await callback_guards.require_private_callback_user(callback)

    assert result is None
    assert callback.answers == [{
        "text": callback_guards.USER_MISSING_TEXT,
        "show_alert": True,
    }]


@pytest.mark.asyncio
async def test_require_admin_message_uses_central_admin_ids(monkeypatch) -> None:
    monkeypatch.setattr(callback_guards, "ADMIN_IDS", [10])

    allowed = FakeMessage(user_id=10)
    denied = FakeMessage(user_id=11)

    assert await callback_guards.require_admin_message(allowed) == 10
    assert await callback_guards.require_admin_message(denied) is None
    assert denied.answers == [{
        "text": callback_guards.ADMIN_ACCESS_DENIED_TEXT,
    }]


@pytest.mark.asyncio
async def test_require_parsed_callback_owner_rejects_mismatch() -> None:
    callback = FakeCallback(
        user_id=1,
        message=FakeMessage(chat_type="private"),
        data="delete:2",
    )

    result = await callback_guards.require_parsed_callback_owner(
        callback,
        lambda data: int(data.rsplit(":", 1)[1]),
    )

    assert result is None
    assert callback.answers == [{
        "text": callback_guards.CALLBACK_OWNER_MISMATCH_TEXT,
        "show_alert": True,
    }]


@pytest.mark.asyncio
async def test_require_parsed_callback_owner_fails_closed_on_parser_error() -> None:
    callback = FakeCallback(
        user_id=1,
        message=FakeMessage(chat_type="private"),
        data="delete:not-an-id",
    )

    result = await callback_guards.require_parsed_callback_owner(
        callback,
        lambda data: int(data.rsplit(":", 1)[1]),
    )

    assert result is None
    assert callback.answers == [{
        "text": callback_guards.CALLBACK_OWNER_MISMATCH_TEXT,
        "show_alert": True,
    }]
