import os
import re

os.environ.setdefault("BOT_TOKEN", "123456:test_bot_token")
os.environ.setdefault("GEMINI_API_KEY", "test_gemini_api_key")
os.environ.setdefault("ADMIN_IDS", "123456789")
os.environ.setdefault("DB_PATH", ":memory:")

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
