import os
import shutil
import uuid
from pathlib import Path

import pytest


os.environ.setdefault("BOT_TOKEN", "123456:test_bot_token")
os.environ.setdefault("GEMINI_API_KEY", "test_gemini_api_key")
os.environ.setdefault("ADMIN_IDS", "123456789")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("READING_SESSION_BACKEND", "memory")
os.environ.setdefault("READING_AUDIO_QUEUE_BACKEND", "memory")
os.environ.setdefault("READING_AUDIO_QUEUE_MAX_SIZE", "20")
os.environ.setdefault("METRICS_REDIS_STREAM_ENABLED", "0")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_RUNTIME_DIR = PROJECT_ROOT / ".test_runtime"


@pytest.fixture
def workspace_tmp_path() -> Path:
    """
    Workspace-local temp directory for Windows setups where pytest/system temp
    folders are not writable or cannot be removed.
    """
    TEST_RUNTIME_DIR.mkdir(exist_ok=True)
    temp_dir = TEST_RUNTIME_DIR / uuid.uuid4().hex
    temp_dir.mkdir()

    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
