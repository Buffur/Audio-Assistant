# Файл: tests/test_text_checks.py

from utils.text_checks import is_error_text
from texts.start import HELP_TEXT


def test_is_error_text_returns_true_for_error_message() -> None:
    assert is_error_text("❌ Помилка читання файлу.") is True


def test_is_error_text_returns_true_with_leading_spaces() -> None:
    assert is_error_text(" ❌ Не вдалося отримати текст.") is True


def test_is_error_text_returns_false_for_regular_text() -> None:
    assert is_error_text("Звичайний текст для озвучення.") is False


def test_is_error_text_returns_false_for_empty_string() -> None:
    assert is_error_text("") is False


def test_is_error_text_returns_false_for_none() -> None:
    assert is_error_text(None) is False


def test_help_text_mentions_supported_languages() -> None:
    assert "Мови:" in HELP_TEXT
    assert "українська" in HELP_TEXT
    assert "англійська" in HELP_TEXT
    assert "німецька" in HELP_TEXT
    assert "польська" in HELP_TEXT
    assert "словацька" in HELP_TEXT
    assert "чеська" in HELP_TEXT


def test_help_text_lists_visible_user_commands() -> None:
    assert "/catalog_clear — очистити каталог" in HELP_TEXT
    assert "/delete_my_data — очистити вашу історію документів" in HELP_TEXT
