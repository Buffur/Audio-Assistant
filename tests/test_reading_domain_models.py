import pytest

from services.reading.domain.models import (
    InvalidReadingSessionError,
    ReadingSession,
)


def test_reading_session_model_normalizes_core_fields_and_preserves_extra() -> None:
    session = ReadingSession.from_mapping(
        {
            "session_id": "session-1",
            "chunks": ["one", "two"],
            "index": "1",
            "is_generating": "true",
            "summary_voice_file_ids": ["file-1"],
            "custom_field": {"kept": True},
        },
        now=123.5,
    )

    assert session.session_id == "session-1"
    assert session.chunks == ["one", "two"]
    assert session.index == 1
    assert session.is_generating is True
    assert session.created_at == 123.5
    assert session.updated_at == 123.5
    assert session.generation_started_at == 123.5
    assert session.extra == {"custom_field": {"kept": True}}
    assert session.to_mapping() == {
        "custom_field": {"kept": True},
        "session_id": "session-1",
        "chunks": ["one", "two"],
        "index": 1,
        "is_generating": True,
        "prefetch_task": None,
        "created_at": 123.5,
        "updated_at": 123.5,
        "generation_started_at": 123.5,
        "summary_voice_file_ids": ["file-1"],
    }


def test_reading_session_model_rejects_missing_session_id() -> None:
    with pytest.raises(InvalidReadingSessionError, match="session_id"):
        ReadingSession.from_mapping(
            {
                "chunks": ["one"],
                "index": 0,
            }
        )


def test_reading_session_model_rejects_invalid_chunks() -> None:
    with pytest.raises(InvalidReadingSessionError, match="chunks"):
        ReadingSession.from_mapping(
            {
                "session_id": "session-1",
                "chunks": ["one", 2],
                "index": 0,
            }
        )


def test_reading_session_model_rejects_negative_index() -> None:
    with pytest.raises(InvalidReadingSessionError, match="index"):
        ReadingSession.from_mapping(
            {
                "session_id": "session-1",
                "chunks": ["one"],
                "index": -1,
            }
        )


def test_reading_session_model_allows_prefetch_reset_sentinel() -> None:
    session = ReadingSession.from_mapping(
        {
            "session_id": "session-1",
            "chunks": ["one"],
            "index": 0,
            "prefetch_state": "none",
            "prefetch_index": -1,
            "prefetch_audio_files": [],
            "prefetch_error": "",
        }
    )

    assert session.prefetch_index == -1
