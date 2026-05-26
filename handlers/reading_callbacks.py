from aiogram import F, Router, types

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
    await callback_flow_service.process_read_next(callback)


@router.callback_query(F.data.startswith(READ_SUMMARY_ACTION))
async def process_read_summary(callback: types.CallbackQuery) -> None:
    await callback_flow_service.process_read_summary(callback)


@router.callback_query(F.data.startswith(READ_EXPORT_AUDIO_ACTION))
async def process_read_export_audio(callback: types.CallbackQuery) -> None:
    await callback_flow_service.process_read_export_audio(callback)


@router.callback_query(F.data.startswith(READ_STOP_ACTION))
async def process_read_stop(callback: types.CallbackQuery) -> None:
    await callback_flow_service.process_read_stop(callback)
