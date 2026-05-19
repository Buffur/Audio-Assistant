import os
import re

import pytest

os.environ.setdefault("BOT_TOKEN", "123456:test_bot_token")
os.environ.setdefault("GEMINI_API_KEY", "test_gemini_api_key")
os.environ.setdefault("ADMIN_IDS", "123456789")
os.environ.setdefault("DB_PATH", ":memory:")

import bot as bot_module
from bot import ADMIN_COMMANDS, MINIMAL_ADMIN_COMMANDS, MINIMAL_USER_COMMANDS, USER_COMMANDS


COMMAND_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")


def _assert_valid_commands(commands) -> None:
    command_names = [command.command for command in commands]

    assert len(command_names) == len(set(command_names))

    for command in commands:
        assert COMMAND_PATTERN.fullmatch(command.command)
        assert 1 <= len(command.description) <= 256


def test_user_commands_are_valid_for_telegram_api() -> None:
    _assert_valid_commands(USER_COMMANDS)


def test_admin_commands_are_valid_for_telegram_api() -> None:
    _assert_valid_commands(ADMIN_COMMANDS)


def test_minimal_fallback_commands_are_valid_for_telegram_api() -> None:
    _assert_valid_commands(MINIMAL_USER_COMMANDS)
    _assert_valid_commands(MINIMAL_ADMIN_COMMANDS)


def test_visible_user_commands_match_regular_user_menu() -> None:
    assert [command.command for command in MINIMAL_USER_COMMANDS] == [
        "start",
        "help",
        "settings",
        "catalog",
        "catalog_clear",
        "usage",
        "privacy",
        "delete_my_data",
    ]


@pytest.mark.asyncio
async def test_setup_bot_commands_can_hide_default_user_commands(monkeypatch) -> None:
    class FakeBot:
        def __init__(self):
            self.calls = []

        async def set_my_commands(self, commands, scope, language_code, request_timeout):
            self.calls.append({
                "method": "set",
                "commands": commands,
                "scope": scope,
                "language_code": language_code,
                "request_timeout": request_timeout,
            })

        async def delete_my_commands(self, scope, language_code, request_timeout):
            self.calls.append({
                "method": "delete",
                "scope": scope,
                "language_code": language_code,
                "request_timeout": request_timeout,
            })

    async def fake_get_all_users():
        raise AssertionError("known users cleanup is disabled by default")

    fake_bot = FakeBot()
    monkeypatch.setattr(bot_module, "HIDE_USER_COMMANDS", True)
    monkeypatch.setattr(bot_module, "ADMIN_IDS", [123])
    monkeypatch.setattr(bot_module, "CLEAR_KNOWN_USER_COMMANDS_ON_STARTUP", False)
    monkeypatch.setattr(bot_module, "get_all_users", fake_get_all_users)

    await bot_module.setup_bot_commands(fake_bot)

    delete_calls = [
        call for call in fake_bot.calls
        if call["method"] == "delete"
    ]
    set_calls = [
        call for call in fake_bot.calls
        if call["method"] == "set"
    ]

    assert len(delete_calls) == 12
    assert len(set_calls) == 5
    assert {call["language_code"] for call in delete_calls} == {
        None,
        "uk",
        "ru",
        "en",
    }
    user_set_calls = [
        call for call in set_calls
        if getattr(call["scope"], "type", None) == "default"
    ]
    admin_set_calls = [
        call for call in set_calls
        if getattr(call["scope"], "chat_id", None) == 123
    ]

    assert len(user_set_calls) == 4
    assert len(admin_set_calls) == 1
    assert {call["language_code"] for call in user_set_calls} == {
        None,
        "uk",
        "ru",
        "en",
    }
    assert [command.command for command in user_set_calls[0]["commands"]] == [
        command.command for command in MINIMAL_USER_COMMANDS
    ]
    assert all(
        getattr(call["scope"], "chat_id", None) is None
        for call in delete_calls
    )
    assert [command.command for command in admin_set_calls[0]["commands"]] == [
        command.command for command in ADMIN_COMMANDS
    ]


@pytest.mark.asyncio
async def test_setup_bot_commands_can_optionally_clear_known_user_chat_scopes(
    monkeypatch,
) -> None:
    class FakeBot:
        def __init__(self):
            self.calls = []

        async def set_my_commands(self, commands, scope, language_code, request_timeout):
            self.calls.append({
                "method": "set",
                "commands": commands,
                "scope": scope,
                "language_code": language_code,
                "request_timeout": request_timeout,
            })

        async def delete_my_commands(self, scope, language_code, request_timeout):
            self.calls.append({
                "method": "delete",
                "scope": scope,
                "language_code": language_code,
                "request_timeout": request_timeout,
            })

    async def fake_get_all_users():
        return [123, 456]

    fake_bot = FakeBot()
    monkeypatch.setattr(bot_module, "HIDE_USER_COMMANDS", True)
    monkeypatch.setattr(bot_module, "ADMIN_IDS", [123])
    monkeypatch.setattr(bot_module, "CLEAR_KNOWN_USER_COMMANDS_ON_STARTUP", True)
    monkeypatch.setattr(bot_module, "get_all_users", fake_get_all_users)

    await bot_module.setup_bot_commands(fake_bot)

    delete_calls = [
        call for call in fake_bot.calls
        if call["method"] == "delete"
    ]

    assert len(delete_calls) == 16
    assert any(
        getattr(call["scope"], "chat_id", None) == 456
        for call in delete_calls
    )
    assert all(
        getattr(call["scope"], "chat_id", None) != 123
        for call in delete_calls
    )
