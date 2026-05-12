# Файл: utils/text_checks.py


def is_error_text(text: str | None) -> bool:
    """
    Перевіряє, чи текст є повідомленням про помилку.

    У поточному проєкті помилки для користувача починаються з символу ❌.
    """
    return bool(text and text.strip().startswith("❌"))