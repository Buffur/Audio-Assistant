# Файл: tests/test_imports.py

import importlib
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PROJECT_PACKAGES = [
    "database",
    "handlers",
    "keyboards",
    "middlewares",
    "services",
    "texts",
    "utils",
]

IGNORED_FILE_NAMES = {
    "__init__.py",
}


def _prepare_test_environment() -> None:
    """
    Задає мінімальні env-змінні для імпорту config.py під час тестів.

    Це потрібно, щоб тести імпортів не залежали від реального .env файлу
    і не вимагали справжніх токенів.
    """
    os.environ.setdefault("BOT_TOKEN", "123456:test_bot_token")
    os.environ.setdefault("GEMINI_API_KEY", "test_gemini_api_key")
    os.environ.setdefault("ADMIN_IDS", "123456789")
    os.environ.setdefault("DB_PATH", ":memory:")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


def _module_name_from_path(file_path: Path) -> str:
    relative_path = file_path.relative_to(PROJECT_ROOT)
    module_parts = list(relative_path.with_suffix("").parts)

    return ".".join(module_parts)


def _iter_project_modules() -> list[str]:
    module_names = ["bot", "config"]

    for package_name in PROJECT_PACKAGES:
        package_path = PROJECT_ROOT / package_name

        if not package_path.exists():
            continue

        for file_path in package_path.rglob("*.py"):
            if file_path.name in IGNORED_FILE_NAMES:
                continue

            module_names.append(_module_name_from_path(file_path))

    return sorted(set(module_names))


_prepare_test_environment()


@pytest.mark.parametrize("module_name", _iter_project_modules())
def test_project_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)