# Файл: handlers/admin.py

import html
import logging

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from database.db import (
    ban_user,
    get_all_users,
    get_all_users_detailed,
    unban_user,
)
from services.telegram_sender import safe_answer_voice, safe_send_voice, sleep_after_send
from services.tts import generate_voice
from services.voice_sender import safe_remove_file

router = Router()
logger = logging.getLogger(__name__)

BROADCAST_VOICE = "uk-UA-PolinaNeural"
BROADCAST_RATE = "+0%"
BROADCAST_DELAY_SECONDS = 0.05
MAX_CAPTION_LENGTH = 1024
MAX_BROADCAST_TEXT_LENGTH = 60000
MAX_BROADCAST_PREVIEW_LENGTH = 1000
BROADCAST_CONFIRM_CALLBACK = "admin_broadcast:confirm"
BROADCAST_CANCEL_CALLBACK = "admin_broadcast:cancel"

_pending_broadcasts: dict[int, str] = {}


def _is_admin_user_id(user_id: int | None) -> bool:
    """
    Перевіряє, чи є user_id адміністратором.
    """
    return bool(user_id and user_id in ADMIN_IDS)


def _is_admin(message: types.Message) -> bool:
    """
    Перевіряє, чи є користувач адміністратором.
    """
    user_id = message.from_user.id if message.from_user else None
    return _is_admin_user_id(user_id)


def _get_command_text(message: types.Message, command: str) -> str:
    """
    Витягує текст після команди.

    Наприклад:
    /broadcast Текст повідомлення -> Текст повідомлення
    """
    if not message.text:
        return ""

    return message.text.replace(command, "", 1).strip()


def _build_broadcast_caption(text_to_send: str) -> str:
    """
    Формує caption для офіційної розсилки.

    Telegram має обмеження на caption до voice-повідомлення,
    тому надто довгий caption обрізається.
    """
    caption_text = f"📢 Офіційне повідомлення від підприємства УТОС\n\n{text_to_send}"

    if len(caption_text) > MAX_CAPTION_LENGTH:
        caption_text = caption_text[:MAX_CAPTION_LENGTH - 3] + "..."

    return caption_text


def _build_broadcast_preview_text(text_to_send: str) -> str:
    safe_text = html.escape(text_to_send)

    if len(safe_text) > MAX_BROADCAST_PREVIEW_LENGTH:
        safe_text = safe_text[:MAX_BROADCAST_PREVIEW_LENGTH - 3] + "..."

    return (
        "📢 <b>Підтвердження розсилки</b>\n\n"
        f"Символів: <b>{len(text_to_send)}</b>\n\n"
        "<b>Текст:</b>\n"
        f"{safe_text}\n\n"
        "Після підтвердження бот згенерує голосове повідомлення "
        "і надішле його всім активним користувачам."
    )


def _broadcast_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Підтвердити",
                callback_data=BROADCAST_CONFIRM_CALLBACK
            ),
            InlineKeyboardButton(
                text="❌ Скасувати",
                callback_data=BROADCAST_CANCEL_CALLBACK
            ),
        ]
    ])


async def _upload_audio_files_to_telegram(
    message: types.Message,
    audio_files: list[str],
    caption_text: str
) -> list[str]:
    """
    Завантажує audio-файли в Telegram через повідомлення адміну
    і повертає список cached file_id.

    Після завантаження локальні файли видаляються.
    """
    cached_file_ids = []

    for audio_path in audio_files:
        try:
            sent_msg = await safe_answer_voice(
                message=message,
                voice=FSInputFile(audio_path),
                caption=caption_text,
            )

            if sent_msg and sent_msg.voice:
                cached_file_ids.append(sent_msg.voice.file_id)
            else:
                logger.warning(
                    "Admin broadcast: Telegram не повернув voice.file_id для файлу: %s",
                    audio_path
                )

        except Exception:
            logger.exception(
                "Admin broadcast: несподівана помилка завантаження audio-файлу: %s",
                audio_path
            )

        finally:
            safe_remove_file(audio_path)

    return cached_file_ids


async def _send_broadcast_to_user(
    bot,
    user_id: int,
    cached_file_ids: list[str],
    caption_text: str
) -> bool:
    """
    Надсилає користувачу всі cached voice-повідомлення розсилки.

    Повертає:
    - True, якщо всі частини відправлено;
    - False, якщо сталася помилка.
    """
    for file_id in cached_file_ids:
        sent_message = await safe_send_voice(
            bot=bot,
            chat_id=user_id,
            voice=file_id,
            caption=caption_text,
        )

        if sent_message is None:
            return False

    return True


def _parse_target_user_id(message: types.Message) -> int | None:
    """
    Парсить user_id з команд /ban та /unban.
    """
    if not message.text:
        return None

    args = message.text.split()

    if len(args) < 2:
        return None

    if not args[1].isdigit():
        return None

    return int(args[1])


async def _run_broadcast(
    message: types.Message,
    admin_id: int,
    text_to_send: str
) -> None:
    logger.info(
        "Admin broadcast: старт генерації розсилки від admin_id=%s, text_length=%s",
        admin_id,
        len(text_to_send)
    )

    status_msg = await message.answer("⏳ Генерую аудіо для розсилки...")

    try:
        audio_files = await generate_voice(
            text=text_to_send,
            voice=BROADCAST_VOICE,
            rate=BROADCAST_RATE
        )

        if not audio_files:
            raise ValueError("Не вдалося згенерувати аудіо.")

    except Exception as error:
        logger.exception("Admin broadcast: помилка генерації аудіо")
        await status_msg.edit_text(f"❌ Помилка генерації: {error}")
        return

    caption_text = _build_broadcast_caption(text_to_send)

    await status_msg.edit_text("🚀 Завантажую аудіо на сервери Telegram...")

    cached_file_ids = await _upload_audio_files_to_telegram(
        message=message,
        audio_files=audio_files,
        caption_text=caption_text
    )

    if not cached_file_ids:
        await status_msg.edit_text("❌ Не вдалося завантажити аудіо для розсилки.")
        return

    users = await get_all_users()

    await status_msg.edit_text(
        f"🚀 Починаю розсилку для {len(users)} користувачів..."
    )

    success_count = 0
    failed_count = 0

    for user_id in users:
        # Адміністратор уже отримав audio під час кешування file_id.
        if user_id == admin_id:
            success_count += 1
            continue

        is_sent = await _send_broadcast_to_user(
            bot=message.bot,
            user_id=user_id,
            cached_file_ids=cached_file_ids,
            caption_text=caption_text
        )

        if is_sent:
            success_count += 1
        else:
            failed_count += 1

        await sleep_after_send(BROADCAST_DELAY_SECONDS)

    logger.info(
        "Admin broadcast: завершено | success=%s | failed=%s | total=%s",
        success_count,
        failed_count,
        len(users)
    )

    await status_msg.edit_text(
        "✅ Розсилку завершено!\n"
        f"Успішно доставлено: {success_count} з {len(users)}.\n"
        f"Не доставлено: {failed_count}."
    )


@router.message(Command("broadcast"))
async def broadcast_message(message: types.Message) -> None:
    if not _is_admin(message):
        return

    admin_id = message.from_user.id
    text_to_send = _get_command_text(message, "/broadcast")

    if not text_to_send:
        await message.answer(
            "❌ Ви не ввели текст. Використання:\n"
            "<code>/broadcast Ваш текст для розсилки</code>",
            parse_mode="HTML"
        )
        return

    if len(text_to_send) > MAX_BROADCAST_TEXT_LENGTH:
        await message.answer(
            f"❌ Текст розсилки занадто великий.\n"
            f"Максимум: {MAX_BROADCAST_TEXT_LENGTH} символів."
        )
        return

    _pending_broadcasts[admin_id] = text_to_send

    await message.answer(
        _build_broadcast_preview_text(text_to_send),
        parse_mode="HTML",
        reply_markup=_broadcast_confirmation_keyboard()
    )


@router.callback_query(F.data == BROADCAST_CONFIRM_CALLBACK)
async def confirm_broadcast_callback(callback: types.CallbackQuery) -> None:
    admin_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user_id(admin_id):
        await callback.answer("У вас немає доступу до розсилки.", show_alert=True)
        return

    text_to_send = _pending_broadcasts.pop(admin_id, None)

    if not text_to_send:
        await callback.answer("Немає активної розсилки для підтвердження.", show_alert=True)
        return

    if not callback.message:
        await callback.answer("Не вдалося знайти повідомлення розсилки.", show_alert=True)
        return

    await callback.answer("Розсилку підтверджено.")
    await callback.message.edit_text("✅ Розсилку підтверджено. Запускаю процес...")
    await _run_broadcast(
        message=callback.message,
        admin_id=admin_id,
        text_to_send=text_to_send
    )


@router.callback_query(F.data == BROADCAST_CANCEL_CALLBACK)
async def cancel_broadcast_callback(callback: types.CallbackQuery) -> None:
    admin_id = callback.from_user.id if callback.from_user else None

    if not _is_admin_user_id(admin_id):
        await callback.answer("У вас немає доступу до розсилки.", show_alert=True)
        return

    _pending_broadcasts.pop(admin_id, None)

    if callback.message:
        await callback.message.edit_text("❌ Розсилку скасовано.")

    await callback.answer("Розсилку скасовано.")


@router.message(Command("users"))
async def list_users_handler(message: types.Message) -> None:
    if not _is_admin(message):
        return

    users = await get_all_users_detailed()

    if not users:
        await message.answer("У базі даних ще немає користувачів.")
        return

    text = "👥 <b>Список користувачів бота:</b>\n\n"

    for idx, user in enumerate(users, 1):
        status = "🚫 ЗАБЛОКОВАНИЙ" if user["is_banned"] else "✅ Активний"

        # БЕЗПЕКА: екрануємо імена та юзернейми,
        # щоб вони не ламали HTML parse mode Telegram.
        safe_full_name = html.escape(str(user["full_name"] or "N/A"))
        safe_username = html.escape(str(user["username"] or "N/A"))

        line = (
            f"{idx}. {safe_full_name} ({safe_username})\n"
            f"   └ ID: <code>{user['user_id']}</code> | {status}\n"
        )

        # Telegram дозволяє до 4096 символів у повідомленні.
        # Залишаємо запас до 4000.
        if len(text) + len(line) > 4000:
            await message.answer(text, parse_mode="HTML")
            text = "👥 <b>Продовження списку:</b>\n\n"

        text += line

    if text and text != "👥 <b>Продовження списку:</b>\n\n":
        await message.answer(text, parse_mode="HTML")


@router.message(Command("ban"))
async def ban_user_handler(message: types.Message) -> None:
    if not _is_admin(message):
        return

    target_id = _parse_target_user_id(message)

    if target_id is None:
        await message.answer(
            "❌ Використання: <code>/ban 123456789</code>",
            parse_mode="HTML"
        )
        return

    if target_id in ADMIN_IDS:
        await message.answer("❌ Ви не можете заблокувати адміністратора!")
        return

    await ban_user(target_id)

    logger.info(
        "Admin: user_id=%s заблокував target_id=%s",
        message.from_user.id,
        target_id
    )

    await message.answer(
        f"✅ Користувача <code>{target_id}</code> заблоковано.",
        parse_mode="HTML"
    )


@router.message(Command("unban"))
async def unban_user_handler(message: types.Message) -> None:
    if not _is_admin(message):
        return

    target_id = _parse_target_user_id(message)

    if target_id is None:
        await message.answer(
            "❌ Використання: <code>/unban 123456789</code>",
            parse_mode="HTML"
        )
        return

    await unban_user(target_id)

    logger.info(
        "Admin: user_id=%s розблокував target_id=%s",
        message.from_user.id,
        target_id
    )

    await message.answer(
        f"✅ Користувача <code>{target_id}</code> розблоковано.",
        parse_mode="HTML"
    )
