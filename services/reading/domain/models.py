from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class InvalidReadingSessionError(ValueError):
    pass


_KNOWN_READING_SESSION_FIELDS = {
    "session_id",
    "chunks",
    "index",
    "is_generating",
    "created_at",
    "updated_at",
    "generation_started_at",
    "generation_finished_at",
    "generation_recovered_at",
    "prefetch_task",
    "prefetch_state",
    "prefetch_index",
    "prefetch_audio_files",
    "prefetch_error",
    "catalog_document_id",
    "summary_text",
    "summary_delivered",
    "summary_voice_file_ids",
    "summary_voice_voice",
    "summary_voice_rate",
    "summary_voice_provider",
}


def _require_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)

    if not isinstance(value, str) or not value.strip():
        raise InvalidReadingSessionError(f"{key} must be a non-empty string")

    return value


def _optional_string(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)

    if value is None:
        return None

    if not isinstance(value, str):
        raise InvalidReadingSessionError(f"{key} must be a string")

    return value


def _optional_float(raw: Mapping[str, Any], key: str) -> float | None:
    value = raw.get(key)

    if value is None:
        return None

    if isinstance(value, bool):
        raise InvalidReadingSessionError(f"{key} must be a number")

    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise InvalidReadingSessionError(f"{key} must be a number") from error


def _integer(
    raw: Mapping[str, Any],
    key: str,
    default: int = 0,
    min_value: int = 0,
) -> int:
    value = raw.get(key, default)

    if isinstance(value, bool):
        raise InvalidReadingSessionError(f"{key} must be an integer")

    try:
        integer_value = int(value)
    except (TypeError, ValueError) as error:
        raise InvalidReadingSessionError(f"{key} must be an integer") from error

    if integer_value < min_value:
        raise InvalidReadingSessionError(f"{key} must be >= {min_value}")

    return integer_value


def _optional_integer(
    raw: Mapping[str, Any],
    key: str,
    min_value: int = 0,
) -> int | None:
    if key not in raw or raw.get(key) is None:
        return None

    return _integer(raw, key, min_value=min_value)


def _boolean(raw: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = raw.get(key, default)

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized_value = value.strip().lower()

        if normalized_value in {"1", "true", "yes"}:
            return True

        if normalized_value in {"0", "false", "no"}:
            return False

    if isinstance(value, int) and value in {0, 1}:
        return bool(value)

    raise InvalidReadingSessionError(f"{key} must be a boolean")


def _optional_boolean(raw: Mapping[str, Any], key: str) -> bool | None:
    if key not in raw or raw.get(key) is None:
        return None

    return _boolean(raw, key)


def _string_list(raw: Mapping[str, Any], key: str, default: list[str] | None = None) -> list[str]:
    value = raw.get(key, default if default is not None else [])

    if not isinstance(value, list):
        raise InvalidReadingSessionError(f"{key} must be a list")

    if not all(isinstance(item, str) for item in value):
        raise InvalidReadingSessionError(f"{key} must contain only strings")

    return list(value)


def _optional_string_list(raw: Mapping[str, Any], key: str) -> list[str] | None:
    if key not in raw or raw.get(key) is None:
        return None

    return _string_list(raw, key)


def _extra_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in raw.items()
        if str(key) not in _KNOWN_READING_SESSION_FIELDS
    }


@dataclass(frozen=True)
class ReadingSession:
    session_id: str
    chunks: list[str]
    index: int = 0
    is_generating: bool = False
    created_at: float | None = None
    updated_at: float | None = None
    generation_started_at: float | None = None
    generation_finished_at: float | None = None
    generation_recovered_at: float | None = None
    prefetch_task: Any | None = None
    prefetch_state: str | None = None
    prefetch_index: int | None = None
    prefetch_audio_files: list[str] | None = None
    prefetch_error: str | None = None
    catalog_document_id: Any | None = None
    summary_text: str | None = None
    summary_delivered: bool | None = None
    summary_voice_file_ids: list[str] | None = None
    summary_voice_voice: str | None = None
    summary_voice_rate: str | None = None
    summary_voice_provider: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls,
        raw_session: Mapping[str, Any],
        *,
        now: float | None = None,
    ) -> "ReadingSession":
        if not isinstance(raw_session, Mapping):
            raise InvalidReadingSessionError("reading session must be a mapping")

        current_time = now
        created_at = _optional_float(raw_session, "created_at")
        updated_at = _optional_float(raw_session, "updated_at")
        is_generating = _boolean(raw_session, "is_generating", default=False)

        if current_time is not None:
            created_at = created_at if created_at is not None else current_time
            updated_at = updated_at if updated_at is not None else current_time

        generation_started_at = _optional_float(
            raw_session,
            "generation_started_at",
        )

        if is_generating and generation_started_at is None and current_time is not None:
            generation_started_at = current_time

        return cls(
            session_id=_require_string(raw_session, "session_id"),
            chunks=_string_list(raw_session, "chunks"),
            index=_integer(raw_session, "index", default=0),
            is_generating=is_generating,
            created_at=created_at,
            updated_at=updated_at,
            generation_started_at=generation_started_at,
            generation_finished_at=_optional_float(
                raw_session,
                "generation_finished_at",
            ),
            generation_recovered_at=_optional_float(
                raw_session,
                "generation_recovered_at",
            ),
            prefetch_task=raw_session.get("prefetch_task"),
            prefetch_state=_optional_string(raw_session, "prefetch_state"),
            prefetch_index=_optional_integer(
                raw_session,
                "prefetch_index",
                min_value=-1,
            ),
            prefetch_audio_files=_optional_string_list(
                raw_session,
                "prefetch_audio_files",
            ),
            prefetch_error=_optional_string(raw_session, "prefetch_error"),
            catalog_document_id=raw_session.get("catalog_document_id"),
            summary_text=_optional_string(raw_session, "summary_text"),
            summary_delivered=_optional_boolean(raw_session, "summary_delivered"),
            summary_voice_file_ids=_optional_string_list(
                raw_session,
                "summary_voice_file_ids",
            ),
            summary_voice_voice=_optional_string(raw_session, "summary_voice_voice"),
            summary_voice_rate=_optional_string(raw_session, "summary_voice_rate"),
            summary_voice_provider=_optional_string(
                raw_session,
                "summary_voice_provider",
            ),
            extra=_extra_fields(raw_session),
        )

    def to_mapping(self) -> dict[str, Any]:
        session = dict(self.extra)
        session.update(
            {
                "session_id": self.session_id,
                "chunks": list(self.chunks),
                "index": self.index,
                "is_generating": self.is_generating,
                "prefetch_task": self.prefetch_task,
            }
        )

        optional_fields = {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "generation_started_at": self.generation_started_at,
            "generation_finished_at": self.generation_finished_at,
            "generation_recovered_at": self.generation_recovered_at,
            "prefetch_state": self.prefetch_state,
            "prefetch_index": self.prefetch_index,
            "prefetch_audio_files": (
                list(self.prefetch_audio_files)
                if self.prefetch_audio_files is not None
                else None
            ),
            "prefetch_error": self.prefetch_error,
            "catalog_document_id": self.catalog_document_id,
            "summary_text": self.summary_text,
            "summary_delivered": self.summary_delivered,
            "summary_voice_file_ids": (
                list(self.summary_voice_file_ids)
                if self.summary_voice_file_ids is not None
                else None
            ),
            "summary_voice_voice": self.summary_voice_voice,
            "summary_voice_rate": self.summary_voice_rate,
            "summary_voice_provider": self.summary_voice_provider,
        }

        session.update(
            {
                key: value
                for key, value in optional_fields.items()
                if value is not None
            }
        )

        return session
