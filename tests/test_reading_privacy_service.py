import pytest
import pytest_asyncio

from services.reading.application import privacy_service
from services.reading.infrastructure import session_store


@pytest_asyncio.fixture(autouse=True)
async def cleanup_privacy_state():
    privacy_service._privacy_delete_markers.clear()
    await session_store.cleanup_all_reading_sessions()
    yield
    privacy_service._privacy_delete_markers.clear()
    await session_store.cleanup_all_reading_sessions()


@pytest.mark.asyncio
async def test_should_skip_deleted_user_job_uses_memory_marker(monkeypatch) -> None:
    monkeypatch.setattr(
        privacy_service,
        "_uses_redis_runtime_state",
        lambda: False,
    )

    user_id = 123

    await privacy_service.mark_user_data_deletion(user_id)

    deleted_at = await privacy_service._get_user_data_deletion_timestamp(user_id)

    assert deleted_at is not None
    assert await privacy_service.should_skip_deleted_user_job(
        user_id,
        deleted_at - 0.01,
    )
    assert not await privacy_service.should_skip_deleted_user_job(
        user_id,
        deleted_at + 0.01,
    )


@pytest.mark.asyncio
async def test_cleanup_user_private_runtime_data_coordinates_dependencies(
    monkeypatch,
) -> None:
    async def fake_purge_queued_audio_jobs_for_user(user_id: int) -> int:
        assert user_id == 88
        return 2

    def fake_delete_user_audio_cache(user_id: int) -> dict[str, int]:
        assert user_id == 88
        return {
            "removed_files": 1,
            "removed_bytes": 1024,
            "owner_links_removed": 3,
        }

    monkeypatch.setattr(
        privacy_service,
        "_uses_redis_runtime_state",
        lambda: False,
    )
    monkeypatch.setattr(
        privacy_service,
        "purge_queued_audio_jobs_for_user",
        fake_purge_queued_audio_jobs_for_user,
    )
    monkeypatch.setattr(
        privacy_service,
        "delete_user_audio_cache",
        fake_delete_user_audio_cache,
    )

    await session_store.set_reading_session(
        user_id=88,
        session={
            "session_id": "private-session",
            "chunks": ["one"],
            "index": 0,
        },
    )

    result = await privacy_service.cleanup_user_private_runtime_data(88)

    assert result == {
        "reading_session": 1,
        "queued_audio_jobs": 2,
        "audio_cache_files": 1,
        "audio_cache_owner_links": 3,
    }
    assert await session_store.get_reading_session(88) is None


@pytest.mark.asyncio
async def test_cleanup_user_private_runtime_data_deletes_only_user_audio_cache(
    monkeypatch,
) -> None:
    captured = {}

    async def fake_purge_queued_audio_jobs_for_user(user_id: int) -> int:
        return 0

    def fake_delete_user_audio_cache(user_id: int) -> dict[str, int]:
        captured["audio_cache_user_id"] = user_id
        return {
            "removed_files": 0,
            "removed_bytes": 0,
            "owner_links_removed": 0,
        }

    monkeypatch.setattr(
        privacy_service,
        "_uses_redis_runtime_state",
        lambda: False,
    )
    monkeypatch.setattr(
        privacy_service,
        "purge_queued_audio_jobs_for_user",
        fake_purge_queued_audio_jobs_for_user,
    )
    monkeypatch.setattr(
        privacy_service,
        "delete_user_audio_cache",
        fake_delete_user_audio_cache,
    )

    result = await privacy_service.cleanup_user_private_runtime_data(88)

    assert captured == {"audio_cache_user_id": 88}
    assert result == {
        "reading_session": 0,
        "queued_audio_jobs": 0,
        "audio_cache_files": 0,
        "audio_cache_owner_links": 0,
    }
