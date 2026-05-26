from dataclasses import dataclass
from typing import Any

from services.reading import audio_queue
from services.reading.domain.models import ReadingSession


@dataclass(frozen=True)
class PrefetchAudioJobCommand:
    user_id: int
    job_created_at: float | None
    session_id: str
    chunk_index: int
    chunk_text: str
    voice: str
    rate: str
    provider_chain: list[str]

    @classmethod
    def from_serialized_job(
        cls,
        job: audio_queue.SerializedAudioJob,
    ) -> "PrefetchAudioJobCommand":
        return cls(
            user_id=int(job["user_id"]),
            job_created_at=float(job.get("created_at") or 0),
            session_id=str(job["session_id"]),
            chunk_index=int(job["chunk_index"]),
            chunk_text=str(job["chunk_text"]),
            voice=str(job["voice"]),
            rate=str(job["rate"]),
            provider_chain=[
                str(provider)
                for provider in job.get("provider_chain", [])
                if str(provider).strip()
            ],
        )


@dataclass(frozen=True)
class ResolvePrefetchedAudioCommand:
    message: Any
    user_id: int
    session: ReadingSession
    chunk_text: str
    voice: str
    rate: str
    provider_chain: list[str]
    current_part: int
    total_parts: int
    status_msg: Any | None = None


@dataclass(frozen=True)
class AudioFilesResult:
    audio_files: list[str]


@dataclass(frozen=True)
class StartPrefetchCommand:
    user_id: int
    session_id: str
    chunks: list[str]
    next_index: int
    voice_pref: str
    rate: str
    tts_provider: str


@dataclass(frozen=True)
class SendAudioChunkNowCommand:
    message: Any
    user_id: int
    expected_session_id: str | None
    status_msg: Any | None
    job_created_at: float | None = None


@dataclass(frozen=True)
class SendAudioChunkCommand:
    message: Any
    user_id: int


@dataclass(frozen=True)
class ExportReadingAudioNowCommand:
    message: Any
    user_id: int
    expected_session_id: str | None
    status_msg: Any | None
    job_created_at: float | None = None


@dataclass(frozen=True)
class ExportReadingAudioCommand:
    message: Any
    user_id: int
    expected_session_id: str | None = None
