# Файл: tests/test_text_checks.py

from utils.text_checks import is_error_text


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