import pytest

from services.reading import audio_queue as reading_audio_queue
from services.reading.audio_job_executor import ReadingAudioJobExecutor


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages = []
        self.sent_voices = []
        self.edits = []
        self.deletes = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return {"message": kwargs}

    async def send_voice(self, **kwargs):
        self.sent_voices.append(kwargs)
        return {"voice": kwargs}

    async def edit_message_text(self, **kwargs) -> None:
        self.edits.append(kwargs)

    async def delete_message(self, **kwargs) -> None:
        self.deletes.append(kwargs)


@pytest.mark.asyncio
async def test_audio_job_executor_dispatches_send_chunk_with_telegram_proxies() -> None:
    captured = {}

    async def should_skip_deleted_user_job(user_id: int, job_created_at: float | None):
        captured["skip_check"] = (user_id, job_created_at)
        return False

    async def fail_prefetch(job) -> None:
        raise AssertionError("send_chunk must not call prefetch runner")

    async def send_audio_chunk_now(**kwargs) -> None:
        captured.update(kwargs)
        await kwargs["message"].answer("queued", disable_notification=True)
        await kwargs["message"].answer_voice(
            "voice-file",
            caption="caption",
            reply_markup="keyboard",
        )
        await kwargs["status_msg"].edit_text("edited")
        await kwargs["status_msg"].delete()

    async def fail_export(**kwargs) -> None:
        raise AssertionError("send_chunk must not call export runner")

    executor = ReadingAudioJobExecutor(
        should_skip_deleted_user_job=should_skip_deleted_user_job,
        run_prefetch_audio_job=fail_prefetch,
        send_audio_chunk_now=send_audio_chunk_now,
        export_reading_audio_now=fail_export,
    )
    bot = FakeBot()

    await executor.run(
        bot,
        reading_audio_queue.build_send_chunk_job(
            user_id=7,
            chat_id=1001,
            session_id="session-1",
            status_message_id=42,
            created_at=123.5,
        ),
    )

    assert captured["skip_check"] == (7, 123.5)
    assert captured["user_id"] == 7
    assert captured["expected_session_id"] == "session-1"
    assert captured["job_created_at"] == 123.5
    assert captured["message"].chat.id == 1001
    assert captured["status_msg"].message_id == 42
    assert bot.sent_messages == [
        {
            "chat_id": 1001,
            "text": "queued",
            "disable_notification": True,
        }
    ]
    assert bot.sent_voices == [
        {
            "chat_id": 1001,
            "voice": "voice-file",
            "caption": "caption",
            "reply_markup": "keyboard",
        }
    ]
    assert bot.edits == [
        {
            "chat_id": 1001,
            "message_id": 42,
            "text": "edited",
        }
    ]
    assert bot.deletes == [
        {
            "chat_id": 1001,
            "message_id": 42,
        }
    ]


@pytest.mark.asyncio
async def test_audio_job_executor_skips_deleted_send_or_export_job() -> None:
    async def should_skip_deleted_user_job(user_id: int, job_created_at: float | None):
        return True

    async def fail_prefetch(job) -> None:
        raise AssertionError("export_audio must not call prefetch runner")

    async def fail_send(**kwargs) -> None:
        raise AssertionError("deleted job must not call send runner")

    async def fail_export(**kwargs) -> None:
        raise AssertionError("deleted job must not call export runner")

    executor = ReadingAudioJobExecutor(
        should_skip_deleted_user_job=should_skip_deleted_user_job,
        run_prefetch_audio_job=fail_prefetch,
        send_audio_chunk_now=fail_send,
        export_reading_audio_now=fail_export,
    )

    await executor.run(
        FakeBot(),
        reading_audio_queue.build_export_audio_job(
            user_id=7,
            chat_id=1001,
            session_id="session-1",
            status_message_id=None,
            created_at=123.5,
        ),
    )


@pytest.mark.asyncio
async def test_audio_job_executor_dispatches_prefetch_without_telegram_adapter() -> None:
    captured = {}

    async def fail_skip(user_id: int, job_created_at: float | None):
        raise AssertionError("prefetch skip policy belongs to the prefetch runner")

    async def run_prefetch_audio_job(job) -> None:
        captured.update(job)

    async def fail_send(**kwargs) -> None:
        raise AssertionError("prefetch must not call send runner")

    async def fail_export(**kwargs) -> None:
        raise AssertionError("prefetch must not call export runner")

    executor = ReadingAudioJobExecutor(
        should_skip_deleted_user_job=fail_skip,
        run_prefetch_audio_job=run_prefetch_audio_job,
        send_audio_chunk_now=fail_send,
        export_reading_audio_now=fail_export,
    )

    await executor.run(
        FakeBot(),
        reading_audio_queue.build_prefetch_chunk_job(
            user_id=7,
            session_id="session-1",
            chunk_index=1,
            chunk_text="text",
            voice="uk-UA-PolinaNeural",
            rate="+0%",
            provider_chain=["edge"],
            created_at=123.5,
        ),
    )

    assert captured == {
        "type": "prefetch_chunk",
        "user_id": 7,
        "session_id": "session-1",
        "chunk_index": 1,
        "chunk_text": "text",
        "voice": "uk-UA-PolinaNeural",
        "rate": "+0%",
        "provider_chain": ["edge"],
        "created_at": 123.5,
    }
