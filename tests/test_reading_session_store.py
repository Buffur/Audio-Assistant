import asyncio
import time

import pytest
from redis.exceptions import RedisError

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
async def test_set_reading_session_normalizes_through_domain_model() -> None:
    await store.cleanup_all_reading_sessions()

    await store.set_reading_session(
        user_id=11,
        session={
            "session_id": "normalized",
            "chunks": ["one"],
            "index": "0",
            "custom_field": "kept",
        },
    )

    session = await store.get_reading_session(11)

    assert session is not None
    assert session["session_id"] == "normalized"
    assert session["chunks"] == ["one"]
    assert session["index"] == 0
    assert session["is_generating"] is False
    assert isinstance(session["created_at"], float)
    assert isinstance(session["updated_at"], float)
    assert session["prefetch_task"] is None
    assert session["custom_field"] == "kept"


def test_deserialize_session_accepts_redis_cjson_empty_optional_lists() -> None:
    session = store.deserialize_session(
        """
        {
            "session_id": "redis-cjson-empty-list",
            "chunks": ["one"],
            "index": 0,
            "prefetch_audio_files": {},
            "summary_voice_file_ids": {}
        }
        """
    )

    assert session is not None
    assert session["prefetch_audio_files"] == []
    assert session["summary_voice_file_ids"] == []


@pytest.mark.asyncio
async def test_get_reading_session_model_returns_domain_model() -> None:
    await store.cleanup_all_reading_sessions()

    await store.set_reading_session(
        user_id=13,
        session={
            "session_id": "typed-session",
            "chunks": ["one", "two"],
            "index": "1",
            "summary_delivered": "true",
        },
    )

    session = await store.get_reading_session_model(13)

    assert session is not None
    assert session.session_id == "typed-session"
    assert session.chunks == ["one", "two"]
    assert session.index == 1
    assert session.summary_delivered is True


@pytest.mark.asyncio
async def test_set_reading_session_rejects_invalid_payload_without_replacing_existing() -> None:
    await store.cleanup_all_reading_sessions()
    await store.set_reading_session(
        user_id=12,
        session={
            "session_id": "valid",
            "chunks": ["one"],
            "index": 0,
        },
    )

    with pytest.raises(store.InvalidReadingSessionError):
        await store.set_reading_session(
            user_id=12,
            session={
                "session_id": "invalid",
                "chunks": ["one"],
                "index": -1,
            },
        )

    session = await store.get_reading_session(12)

    assert session is not None
    assert session["session_id"] == "valid"
    assert session["index"] == 0


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


@pytest.mark.asyncio
async def test_stale_generation_is_recovered() -> None:
    await store.cleanup_all_reading_sessions()

    await store.set_reading_session(
        user_id=3,
        session={
            "session_id": "stale-generation",
            "chunks": ["one"],
            "index": 0,
            "is_generating": True,
            "generation_started_at": time.time()
            - store.GENERATION_STALE_SECONDS
            - 1,
            "updated_at": time.time(),
        },
    )

    session = await store.get_reading_session(3)

    assert session is not None
    assert session["is_generating"] is False
    assert "generation_recovered_at" in session


@pytest.mark.asyncio
async def test_non_stale_generation_lock_blocks_new_generation() -> None:
    await store.cleanup_all_reading_sessions()
    started_at = time.time()

    await store.set_reading_session(
        user_id=4,
        session={
            "session_id": "active-generation",
            "chunks": ["one"],
            "index": 0,
            "is_generating": True,
            "generation_started_at": started_at,
            "updated_at": started_at,
        },
    )

    assert await store.try_start_generation(4) is False

    session = await store.get_reading_session(4)

    assert session is not None
    assert session["is_generating"] is True
    assert session["generation_started_at"] == pytest.approx(started_at)
    assert "generation_recovered_at" not in session


@pytest.mark.asyncio
async def test_stale_generation_lock_is_recovered_before_restart() -> None:
    await store.cleanup_all_reading_sessions()
    stale_started_at = time.time() - store.GENERATION_STALE_SECONDS - 1

    await store.set_reading_session(
        user_id=5,
        session={
            "session_id": "stale-generation-restart",
            "chunks": ["one"],
            "index": 0,
            "is_generating": True,
            "generation_started_at": stale_started_at,
            "updated_at": stale_started_at,
        },
    )

    assert await store.try_start_generation(5) is True

    session = await store.get_reading_session(5)

    assert session is not None
    assert session["is_generating"] is True
    assert session["generation_started_at"] > stale_started_at
    assert session["generation_recovered_at"] > stale_started_at


@pytest.mark.asyncio
async def test_redis_backend_fails_closed_on_get_error(monkeypatch) -> None:
    async def fail_redis_client():
        raise RedisError("redis down")

    monkeypatch.setattr(store, "READING_SESSION_BACKEND", "redis")
    monkeypatch.setattr(store, "get_redis_client", fail_redis_client)

    with pytest.raises(store.ReadingSessionStoreUnavailableError):
        await store.get_reading_session(4)
