import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Protocol

from aiogram import Bot

from services.reading.audio_queue import SerializedAudioJob

logger = logging.getLogger(__name__)

ShouldSkipDeletedUserJob = Callable[[int, float | None], Awaitable[bool]]
PrefetchAudioJobRunner = Callable[[SerializedAudioJob], Awaitable[None]]


class AudioChunkSender(Protocol):
    def __call__(
        self,
        *,
        message: Any,
        user_id: int,
        expected_session_id: str,
        status_msg: Any | None,
        job_created_at: float | None = None,
    ) -> Awaitable[None]:
        ...


class AudioExportRunner(Protocol):
    def __call__(
        self,
        *,
        message: Any,
        user_id: int,
        expected_session_id: str,
        status_msg: Any | None,
        job_created_at: float | None = None,
    ) -> Awaitable[None]:
        ...


class TelegramWorkerMessageProxy:
    def __init__(self, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat = SimpleNamespace(id=chat_id)

    async def answer(self, text: str, **kwargs: object) -> Any:
        return await self.bot.send_message(
            chat_id=self.chat.id,
            text=text,
            **kwargs,
        )

    async def answer_voice(
        self,
        voice: Any,
        caption: str | None = None,
        reply_markup: Any | None = None,
    ) -> Any:
        return await self.bot.send_voice(
            chat_id=self.chat.id,
            voice=voice,
            caption=caption,
            reply_markup=reply_markup,
        )


class TelegramWorkerStatusMessageProxy:
    def __init__(self, bot: Bot, chat_id: int, message_id: int) -> None:
        self.bot = bot
        self.chat = SimpleNamespace(id=chat_id)
        self.message_id = message_id

    async def edit_text(self, text: str) -> None:
        await self.bot.edit_message_text(
            chat_id=self.chat.id,
            message_id=self.message_id,
            text=text,
        )

    async def delete(self) -> None:
        await self.bot.delete_message(
            chat_id=self.chat.id,
            message_id=self.message_id,
        )


@dataclass(frozen=True)
class ReadingAudioJobExecutor:
    should_skip_deleted_user_job: ShouldSkipDeletedUserJob
    run_prefetch_audio_job: PrefetchAudioJobRunner
    send_audio_chunk_now: AudioChunkSender
    export_reading_audio_now: AudioExportRunner

    async def run(self, bot: Bot, job: SerializedAudioJob) -> None:
        job_type = str(job.get("type") or "")

        if job_type == "prefetch_chunk":
            await self.run_prefetch_audio_job(job)
            return

        user_id = int(job["user_id"])
        job_created_at = float(job.get("created_at") or 0)
        chat_id = int(job["chat_id"])
        expected_session_id = str(job["session_id"])
        status_message_id = job.get("status_message_id")

        if await self.should_skip_deleted_user_job(user_id, job_created_at):
            return

        message = TelegramWorkerMessageProxy(bot, chat_id)
        status_msg = (
            TelegramWorkerStatusMessageProxy(bot, chat_id, int(status_message_id))
            if isinstance(status_message_id, int)
            else None
        )

        if job_type == "send_chunk":
            await self.send_audio_chunk_now(
                message=message,
                user_id=user_id,
                expected_session_id=expected_session_id,
                status_msg=status_msg,
                job_created_at=job_created_at,
            )
            return

        if job_type == "export_audio":
            await self.export_reading_audio_now(
                message=message,
                user_id=user_id,
                expected_session_id=expected_session_id,
                status_msg=status_msg,
                job_created_at=job_created_at,
            )
            return

        logger.warning("ReadingAudioJobExecutor: unknown audio job type=%s", job_type)
