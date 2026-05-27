from aiogram import F, Router, types

from handlers.callback_guards import require_private_callback_user
from keyboards.reading import (
    READ_EXPORT_AUDIO_ACTION,
    READ_NEXT_ACTION,
    READ_STOP_ACTION,
    READ_SUMMARY_ACTION,
)
from services.reading.application import callback_flow_service

router = Router()

ReadingCallbackContext = callback_flow_service.ReadingCallbackContext

SUMMARY_AUDIO_GENERATION_ERROR = callback_flow_service.SUMMARY_AUDIO_GENERATION_ERROR
SUMMARY_CAPTION_TEXT = callback_flow_service.SUMMARY_CAPTION_TEXT
SUMMARY_GENERATION_ERROR = callback_flow_service.SUMMARY_GENERATION_ERROR
SUMMARY_PREPARING_TEXT = callback_flow_service.SUMMARY_PREPARING_TEXT

_get_catalog_document_id = callback_flow_service._get_catalog_document_id
_is_matching_session = callback_flow_service._is_matching_session


async def _dispatch_reading_callback(callback: types.CallbackQuery, processor) -> None:
    if await require_private_callback_user(callback) is None:
        return

    await processor(callback)


async def _get_reading_callback_context(
    callback: types.CallbackQuery,
    *,
    missing_text: str,
) -> ReadingCallbackContext | None:
    return await callback_flow_service._get_reading_callback_context(
        callback,
        missing_text=missing_text,
    )


@router.callback_query(F.data.startswith(READ_NEXT_ACTION))
async def process_read_next(callback: types.CallbackQuery) -> None:
    await _dispatch_reading_callback(
        callback,
        callback_flow_service.process_read_next,
    )


@router.callback_query(F.data.startswith(READ_SUMMARY_ACTION))
async def process_read_summary(callback: types.CallbackQuery) -> None:
    await _dispatch_reading_callback(
        callback,
        callback_flow_service.process_read_summary,
    )


@router.callback_query(F.data.startswith(READ_EXPORT_AUDIO_ACTION))
async def process_read_export_audio(callback: types.CallbackQuery) -> None:
    await _dispatch_reading_callback(
        callback,
        callback_flow_service.process_read_export_audio,
    )


@router.callback_query(F.data.startswith(READ_STOP_ACTION))
async def process_read_stop(callback: types.CallbackQuery) -> None:
    await _dispatch_reading_callback(
        callback,
        callback_flow_service.process_read_stop,
    )
