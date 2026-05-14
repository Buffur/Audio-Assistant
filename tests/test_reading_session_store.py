import asyncio

import pytest

from services import reading_session_store as store


@pytest.mark.asyncio
async def test_reading_session_lifecycle() -> None:
    await store.cleanup_all_reading_sessions()

    await store.set_reading_session(
        user_id=1,
        session={
            "session_id": "abc",
            "chunks": ["one", "two"],
            "index": 0,
        },
    )

    session = await store.get_reading_session(1)
    assert session is not None
    assert session["session_id"] == "abc"

    await store.update_reading_session(1, index=1)
    assert (await store.get_reading_session(1))["index"] == 1

    assert await store.try_start_generation(1) is True
    assert await store.try_start_generation(1) is False

    await store.finish_generation(1)
    assert await store.try_start_generation(1) is True

    await store.cleanup_reading_session(1)
    assert await store.get_reading_session(1) is None


@pytest.mark.asyncio
async def test_cleanup_prefetch_task_removes_completed_audio_files(workspace_tmp_path) -> None:
    audio_path = workspace_tmp_path / "voice.ogg"
    audio_path.write_bytes(b"voice")

    async def completed_task():
        return [str(audio_path)]

    task = asyncio.create_task(completed_task())
    await task

    await store.set_reading_session(
        user_id=2,
        session={
            "session_id": "prefetch",
            "chunks": ["one"],
            "index": 0,
            "prefetch_task": task,
        },
    )
    await store.cleanup_reading_session(2)

    assert not audio_path.exists()
