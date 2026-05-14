# Файл: services/reading_service.py

import asyncio
import logging
from contextlib import suppress

from aiogram.types import Message

from keyboards.reading import reading_navigation_keyboard
from services.reading_session_store import (
    cleanup_reading_session,
    get_reading_session,
    update_reading_session,
)
from services.tts import generate_voice
from services.user_settings_service import (
    build_user_tts_provider_chain,
    get_effective_user_settings,
    get_effective_user_tts_provider,
)
from services.voice_selector import select_voice_for_text
from services.voice_sender import send_voice_files

logger = logging.getLogger(__name__)


async def safe_delete_message(message: Message | None) -> None:
    """
    Безпечно видаляє повідомлення.
    Якщо Telegram не дозволив видалення — просто ігноруємо.
    """
    if message is None:
        return

    with suppress(Exception):
        await message.delete()


async def cleanup_session(user_id: int) -> None:
    """
    Public wrapper для handlers.
    """
    await cleanup_reading_session(user_id)


async def _send_audio_files(
    message: Message,
    audio_files: list[str],
    caption: str | None = None,
    reply_markup=None,
) -> None:
    """
    Надсилає audio-файли як voice і завжди видаляє тимчасові файли.
    """
    await send_voice_files(
        message=message,
        audio_files=audio_files,
        caption=caption,
        reply_markup=reply_markup,
    )


async def reply_with_voice(
    message: Message,
    user_id: int,
    text: str,
    status_msg: Message | None = None,
) -> None:
    """
    Надсилає службовий текст голосом.
    Якщо TTS не спрацював — надсилає звичайний текст.
    """
    await safe_delete_message(status_msg)

    clean_text = (
        text.replace("❌", "")
        .replace("✅", "")
        .replace("🛑", "")
        .replace("📚", "")
        .replace("⏳", "")
        .replace("📝", "")
        .strip()
    )

    if not clean_text:
        await message.answer(text)
        return

    try:
        voice_pref, rate = await get_effective_user_settings(user_id)
        tts_provider = await get_effective_user_tts_provider(user_id)
        voice = select_voice_for_text(clean_text, voice_pref)

        audio_files = await generate_voice(
            text=clean_text,
            voice=voice,
            rate=rate,
            provider_chain=build_user_tts_provider_chain(
                tts_provider,
                voice=voice,
            ),
        )

        if not audio_files:
            await message.answer(text)
            return

        await _send_audio_files(
            message=message,
            audio_files=audio_files,
            caption=text,
        )

    except Exception:
        logger.exception(
            "ReadingService: не вдалося озвучити службове повідомлення user_id=%s",
            user_id,
        )
        await message.answer(text)


async def _get_audio_from_prefetch_or_generate(
    *,
    message: Message,
    user_id: int,
    session: dict,
    chunk_text: str,
    voice: str,
    rate: str,
    provider_chain: list[str],
) -> list[str]:
    """
    Бере аудіо з prefetch_task або генерує його вручну.
    """
    prefetch_task = session.get("prefetch_task")
    status_msg: Message | None = None

    if prefetch_task:
        if not prefetch_task.done():
            status_msg = await message.answer("⏳ Довантажую наступну частину.")

        try:
            audio_files = await prefetch_task

        except asyncio.CancelledError:
            logger.info(
                "ReadingService: prefetch_task скасовано, генерую вручну user_id=%s",
                user_id,
            )
            audio_files = await generate_voice(
                chunk_text,
                voice,
                rate,
                provider_chain=provider_chain,
            )

        except Exception:
            logger.exception(
                "ReadingService: помилка prefetch_task, генерую вручну user_id=%s",
                user_id,
            )
            audio_files = await generate_voice(
                chunk_text,
                voice,
                rate,
                provider_chain=provider_chain,
            )

        await update_reading_session(user_id, prefetch_task=None)
        await safe_delete_message(status_msg)
        return audio_files

    status_msg = await message.answer("⏳ Генерую аудіо.")

    try:
        audio_files = await generate_voice(
            chunk_text,
            voice,
            rate,
            provider_chain=provider_chain,
        )
        return audio_files

    finally:
        await safe_delete_message(status_msg)


async def _start_prefetch_next_chunk(
    *,
    user_id: int,
    chunks: list[str],
    next_index: int,
    voice_pref: str,
    rate: str,
    tts_provider: str,
) -> None:
    """
    Запускає фонову генерацію наступної частини.
    """
    if next_index >= len(chunks):
        return

    next_chunk = chunks[next_index]
    next_voice = select_voice_for_text(next_chunk, voice_pref)
    provider_chain = build_user_tts_provider_chain(
        tts_provider,
        voice=next_voice,
    )

    prefetch_task = asyncio.create_task(
        generate_voice(
            text=next_chunk,
            voice=next_voice,
            rate=rate,
            provider_chain=provider_chain,
        )
    )

    await update_reading_session(
        user_id,
        prefetch_task=prefetch_task,
    )


async def send_audio_chunk(message: Message, user_id: int) -> None:
    """
    Надсилає поточну частину тексту голосом і запускає prefetch наступної.
    """
    session = await get_reading_session(user_id)

    if not session:
        await message.answer("❌ Сесія читання не знайдена або вже завершена.")
        return

    chunks = session.get("chunks") or []
    index = int(session.get("index", 0))
    session_id = session.get("session_id", "legacy")

    if not chunks:
        await cleanup_session(user_id)
        await message.answer("❌ У сесії немає тексту для читання.")
        return

    if index >= len(chunks):
        await cleanup_session(user_id)
        await message.answer("✅ Всі частини вже були надіслані.")
        return

    chunk_text = chunks[index]

    voice_pref, rate = await get_effective_user_settings(user_id)
    tts_provider = await get_effective_user_tts_provider(user_id)
    voice = select_voice_for_text(chunk_text, voice_pref)
    provider_chain = build_user_tts_provider_chain(tts_provider, voice=voice)

    try:
        audio_files = await _get_audio_from_prefetch_or_generate(
            message=message,
            user_id=user_id,
            session=session,
            chunk_text=chunk_text,
            voice=voice,
            rate=rate,
            provider_chain=provider_chain,
        )

        if not audio_files:
            logger.warning(
                "ReadingService: TTS повернув порожній список user_id=%s, index=%s",
                user_id,
                index,
            )
            await message.answer("❌ Не вдалося згенерувати аудіо для цієї частини.")
            return

        new_index = index + 1
        has_next = new_index < len(chunks)

        await update_reading_session(
            user_id,
            index=new_index,
        )

        keyboard = reading_navigation_keyboard(
            has_next=has_next,
            session_id=session_id,
        )

        await _send_audio_files(
            message=message,
            audio_files=audio_files,
            caption=f"📄 Частина {index + 1} з {len(chunks)}",
            reply_markup=keyboard,
        )

        if not has_next:
            await message.answer(
                "✅ Всі частини надіслано. "
                "Ви можете прослухати короткий зміст або завершити роботу з матеріалом."
            )
            return

        await _start_prefetch_next_chunk(
            user_id=user_id,
            chunks=chunks,
            next_index=new_index,
            voice_pref=voice_pref,
            rate=rate,
            tts_provider=tts_provider,
        )

    except Exception:
        logger.exception(
            "ReadingService: помилка надсилання audio chunk user_id=%s, index=%s",
            user_id,
            index,
        )
        await message.answer("❌ Сталася помилка під час генерації аудіо.")
