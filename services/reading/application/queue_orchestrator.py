import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from redis.exceptions import RedisError

from services.reading import audio_queue
from services.reading.application.commands import (
    ExportReadingAudioNowCommand,
    SendAudioChunkNowCommand,
)
from texts.messages import (
    build_audio_generation_queued_text,
    build_export_audio_queued_text,
)

logger = logging.getLogger(__name__)

QueueBackend = Literal["redis", "memory"]
QueueEnqueueStatus = Literal["queued", "full", "failed"]

AudioGenerationJob = audio_queue.AudioGenerationJob
SerializedAudioJob = audio_queue.SerializedAudioJob

AsyncIntSupplier = Callable[[], Awaitable[int]]
IntSupplier = Callable[[], int]
BoolSupplier = Callable[[], bool]
EnqueueRedisAudioJob = Callable[[SerializedAudioJob], Awaitable[None]]
EnqueueMemoryAudioJob = Callable[[AudioGenerationJob], None]
GetQueueStats = Callable[[], Awaitable[audio_queue.AudioQueueStats]]
SendAudioChunkNow = Callable[[SendAudioChunkNowCommand], Awaitable[None]]
ExportReadingAudioNow = Callable[[ExportReadingAudioNowCommand], Awaitable[None]]
MemoryPrefetchAudioJob = Callable[[], Awaitable[list[str]]]


@dataclass(frozen=True)
class QueueEnqueueResult:
    status: QueueEnqueueStatus
    backend: QueueBackend
    status_msg: Any | None = None
    memory_task: asyncio.Future[list[str]] | None = None
    error: BaseException | None = None
    queue_stats: audio_queue.AudioQueueStats | None = None

    @property
    def queued(self) -> bool:
        return self.status == "queued"


@dataclass(frozen=True)
class SendChunkAudioEnqueueCommand:
    message: Any
    user_id: int
    session_id: str
    current_part: int
    total_parts: int
    run_now: SendAudioChunkNow


@dataclass(frozen=True)
class ExportAudioEnqueueCommand:
    message: Any
    user_id: int
    session_id: str
    total_parts: int
    run_now: ExportReadingAudioNow


@dataclass(frozen=True)
class PrefetchAudioEnqueueCommand:
    user_id: int
    session_id: str
    chunk_index: int
    chunk_text: str
    voice: str
    rate: str
    provider_chain: list[str]
    memory_audio_job: MemoryPrefetchAudioJob


def _message_chat_id(message: Any) -> int | None:
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)

    if isinstance(chat_id, int):
        return chat_id

    return None


def _status_message_id(message: Any | None) -> int | None:
    message_id = getattr(message, "message_id", None)

    if isinstance(message_id, int):
        return message_id

    return None


@dataclass(frozen=True)
class ReadingAudioQueueOrchestrator:
    use_redis_audio_queue: BoolSupplier
    redis_audio_queue_position: AsyncIntSupplier
    enqueue_redis_audio_job: EnqueueRedisAudioJob
    memory_audio_queue_position: IntSupplier
    enqueue_memory_audio_job: EnqueueMemoryAudioJob
    get_queue_stats: GetQueueStats

    def should_use_redis_backend(self) -> bool:
        return self.use_redis_audio_queue()

    async def _backpressure_result(
        self,
        backend: QueueBackend,
        *,
        use_case: str,
        user_id: int,
    ) -> QueueEnqueueResult | None:
        try:
            stats = await self.get_queue_stats()

        except Exception as error:
            logger.exception(
                "ReadingQueueOrchestrator: failed to read queue stats "
                "use_case=%s user_id=%s backend=%s",
                use_case,
                user_id,
                backend,
            )
            return QueueEnqueueResult(
                status="failed",
                backend=backend,
                error=error,
            )

        if stats.degraded or stats.active is None:
            logger.warning(
                "ReadingQueueOrchestrator: queue stats degraded "
                "use_case=%s user_id=%s backend=%s error=%s",
                use_case,
                user_id,
                backend,
                stats.error,
            )
            return QueueEnqueueResult(
                status="failed",
                backend=backend,
                queue_stats=stats,
            )

        if stats.is_full:
            logger.warning(
                "ReadingQueueOrchestrator: queue backpressure rejected enqueue "
                "use_case=%s user_id=%s backend=%s active=%s max_size=%s",
                use_case,
                user_id,
                backend,
                stats.active,
                stats.max_size,
            )
            return QueueEnqueueResult(
                status="full",
                backend=backend,
                queue_stats=stats,
            )

        return None

    async def enqueue_send_chunk_audio(
        self,
        command: SendChunkAudioEnqueueCommand,
    ) -> QueueEnqueueResult:
        job_created_at = time.time()
        chat_id = _message_chat_id(command.message)

        if self.should_use_redis_backend() and chat_id is not None:
            backpressure_result = await self._backpressure_result(
                "redis",
                use_case="send_chunk",
                user_id=command.user_id,
            )

            if backpressure_result is not None:
                return backpressure_result

            status_msg = None

            try:
                queued_position = await self.redis_audio_queue_position()
                status_msg = await command.message.answer(
                    build_audio_generation_queued_text(
                        current_part=command.current_part,
                        total_parts=command.total_parts,
                        queue_position=queued_position,
                    )
                )
                await self.enqueue_redis_audio_job(
                    audio_queue.build_send_chunk_job(
                        user_id=command.user_id,
                        chat_id=chat_id,
                        session_id=command.session_id,
                        status_message_id=_status_message_id(status_msg),
                        created_at=job_created_at,
                    )
                )
                return QueueEnqueueResult(
                    status="queued",
                    backend="redis",
                    status_msg=status_msg,
                )

            except asyncio.QueueFull as error:
                logger.warning(
                    "ReadingQueueOrchestrator: Redis queue is full "
                    "use_case=send_chunk user_id=%s",
                    command.user_id,
                )
                return QueueEnqueueResult(
                    status="full",
                    backend="redis",
                    status_msg=status_msg,
                    error=error,
                )

            except RedisError as error:
                logger.exception(
                    "ReadingQueueOrchestrator: Redis enqueue failed "
                    "use_case=send_chunk user_id=%s",
                    command.user_id,
                )
                return QueueEnqueueResult(
                    status="failed",
                    backend="redis",
                    status_msg=status_msg,
                    error=error,
                )

        if not self.should_use_redis_backend():
            backpressure_result = await self._backpressure_result(
                "memory",
                use_case="send_chunk",
                user_id=command.user_id,
            )

            if backpressure_result is not None:
                return backpressure_result

        queued_position = self.memory_audio_queue_position()
        status_msg = await command.message.answer(
            build_audio_generation_queued_text(
                current_part=command.current_part,
                total_parts=command.total_parts,
                queue_position=queued_position,
            )
        )

        async def job() -> None:
            await command.run_now(
                SendAudioChunkNowCommand(
                    message=command.message,
                    user_id=command.user_id,
                    expected_session_id=command.session_id,
                    status_msg=status_msg,
                    job_created_at=job_created_at,
                )
            )

        try:
            audio_queue.set_audio_generation_job_metadata(
                job,
                user_id=command.user_id,
                job_type="send_chunk",
            )
            self.enqueue_memory_audio_job(job)
            return QueueEnqueueResult(
                status="queued",
                backend="memory",
                status_msg=status_msg,
            )

        except asyncio.QueueFull as error:
            return QueueEnqueueResult(
                status="full",
                backend="memory",
                status_msg=status_msg,
                error=error,
            )

    async def enqueue_export_audio(
        self,
        command: ExportAudioEnqueueCommand,
    ) -> QueueEnqueueResult:
        job_created_at = time.time()
        chat_id = _message_chat_id(command.message)

        if self.should_use_redis_backend() and chat_id is not None:
            backpressure_result = await self._backpressure_result(
                "redis",
                use_case="export_audio",
                user_id=command.user_id,
            )

            if backpressure_result is not None:
                return backpressure_result

            status_msg = None

            try:
                queued_position = await self.redis_audio_queue_position()
                status_msg = await command.message.answer(
                    build_export_audio_queued_text(
                        total_parts=command.total_parts,
                        queue_position=queued_position,
                    )
                )
                await self.enqueue_redis_audio_job(
                    audio_queue.build_export_audio_job(
                        user_id=command.user_id,
                        chat_id=chat_id,
                        session_id=command.session_id,
                        status_message_id=_status_message_id(status_msg),
                        created_at=job_created_at,
                    )
                )
                return QueueEnqueueResult(
                    status="queued",
                    backend="redis",
                    status_msg=status_msg,
                )

            except asyncio.QueueFull as error:
                logger.warning(
                    "ReadingQueueOrchestrator: Redis queue is full "
                    "use_case=export_audio user_id=%s",
                    command.user_id,
                )
                return QueueEnqueueResult(
                    status="full",
                    backend="redis",
                    status_msg=status_msg,
                    error=error,
                )

            except RedisError as error:
                logger.exception(
                    "ReadingQueueOrchestrator: Redis enqueue failed "
                    "use_case=export_audio user_id=%s",
                    command.user_id,
                )
                return QueueEnqueueResult(
                    status="failed",
                    backend="redis",
                    status_msg=status_msg,
                    error=error,
                )

        if not self.should_use_redis_backend():
            backpressure_result = await self._backpressure_result(
                "memory",
                use_case="export_audio",
                user_id=command.user_id,
            )

            if backpressure_result is not None:
                return backpressure_result

        queued_position = self.memory_audio_queue_position()
        status_msg = await command.message.answer(
            build_export_audio_queued_text(
                total_parts=command.total_parts,
                queue_position=queued_position,
            )
        )

        async def job() -> None:
            await command.run_now(
                ExportReadingAudioNowCommand(
                    message=command.message,
                    user_id=command.user_id,
                    expected_session_id=command.session_id,
                    status_msg=status_msg,
                    job_created_at=job_created_at,
                )
            )

        try:
            audio_queue.set_audio_generation_job_metadata(
                job,
                user_id=command.user_id,
                job_type="export_audio",
            )
            self.enqueue_memory_audio_job(job)
            return QueueEnqueueResult(
                status="queued",
                backend="memory",
                status_msg=status_msg,
            )

        except asyncio.QueueFull as error:
            return QueueEnqueueResult(
                status="full",
                backend="memory",
                status_msg=status_msg,
                error=error,
            )

    async def enqueue_prefetch_audio(
        self,
        command: PrefetchAudioEnqueueCommand,
    ) -> QueueEnqueueResult:
        if self.should_use_redis_backend():
            backpressure_result = await self._backpressure_result(
                "redis",
                use_case="prefetch_chunk",
                user_id=command.user_id,
            )

            if backpressure_result is not None:
                return backpressure_result

            try:
                await self.enqueue_redis_audio_job(
                    audio_queue.build_prefetch_chunk_job(
                        user_id=command.user_id,
                        session_id=command.session_id,
                        chunk_index=command.chunk_index,
                        chunk_text=command.chunk_text,
                        voice=command.voice,
                        rate=command.rate,
                        provider_chain=command.provider_chain,
                        created_at=time.time(),
                    )
                )
                return QueueEnqueueResult(status="queued", backend="redis")

            except asyncio.QueueFull as error:
                logger.warning(
                    "ReadingQueueOrchestrator: Redis queue is full "
                    "use_case=prefetch_chunk user_id=%s",
                    command.user_id,
                )
                return QueueEnqueueResult(
                    status="full",
                    backend="redis",
                    error=error,
                )

            except RedisError as error:
                logger.exception(
                    "ReadingQueueOrchestrator: Redis enqueue failed "
                    "use_case=prefetch_chunk user_id=%s",
                    command.user_id,
                )
                return QueueEnqueueResult(
                    status="failed",
                    backend="redis",
                    error=error,
                )

        if not self.should_use_redis_backend():
            backpressure_result = await self._backpressure_result(
                "memory",
                use_case="prefetch_chunk",
                user_id=command.user_id,
            )

            if backpressure_result is not None:
                return backpressure_result

        loop = asyncio.get_running_loop()
        memory_task: asyncio.Future[list[str]] = loop.create_future()

        async def job() -> None:
            try:
                result = await command.memory_audio_job()
                if not memory_task.done():
                    memory_task.set_result(result)
            except Exception as error:
                if not memory_task.done():
                    memory_task.set_exception(error)

        audio_queue.set_audio_generation_job_metadata(
            job,
            user_id=command.user_id,
            job_type="prefetch_chunk",
        )
        self.enqueue_memory_audio_job(job)

        return QueueEnqueueResult(
            status="queued",
            backend="memory",
            memory_task=memory_task,
        )
