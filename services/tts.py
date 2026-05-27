# Файл: services/tts.py

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import edge_tts

from config import (
    EDGE_TTS_REQUEST_TIMEOUT_SECONDS,
    GEMINI_TTS_CHUNK_MAX_LENGTH,
    GEMINI_TTS_MODEL,
    GEMINI_TTS_MODEL_CHAIN,
    GEMINI_TTS_STYLE_PROMPT,
    TTS_PROVIDER,
    TTS_PROVIDER_CHAIN,
)
from services.audio_cache import get_audio_from_cache, save_audio_to_cache
from services.gemini_client import (
    GeminiFallbackExhaustedError,
    GeminiModelUnavailableError,
    GeminiQuotaExceededError,
)
from services.gemini_tts import (
    GEMINI_TTS_CONTINUITY_PROMPT,
    generate_gemini_tts_ogg,
    get_gemini_tts_voice,
)
from services.telemetry_service import record_service_metric
from utils.audio import convert_to_ogg, create_temp_file_path, safe_remove_file
from utils.splitter import MAX_LENGTH as DEFAULT_TTS_CHUNK_MAX_LENGTH
from utils.splitter import split_text

logger = logging.getLogger(__name__)

TTS_CONCURRENCY_LIMIT = 2
TTS_RETRY_ATTEMPTS = 3
TTS_RETRY_BASE_DELAY_SECONDS = 0.8

tts_semaphore = asyncio.Semaphore(TTS_CONCURRENCY_LIMIT)

TTS_PROVIDER_NAMES = {"edge", "gemini"}

TTSProgressCallback = Callable[[int, int, str, bool], Awaitable[None]]
GenerateChunkCallable = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class TTSProviderSpec:
    chunk_max_length: int
    cache_voice_name: Callable[[str], str]
    generate_chunk: GenerateChunkCallable
    record_local_metrics: bool


def _is_expected_provider_failure(error: Exception) -> bool:
    return isinstance(
        error,
        (
            GeminiFallbackExhaustedError,
            GeminiModelUnavailableError,
            GeminiQuotaExceededError,
        ),
    )


def _gemini_cache_voice_name(edge_voice: str) -> str:
    model_chain = ",".join(
        [GEMINI_TTS_MODEL, *GEMINI_TTS_MODEL_CHAIN]
    )

    return (
        f"gemini:{model_chain}:"
        f"{get_gemini_tts_voice(edge_voice)}:"
        f"{GEMINI_TTS_STYLE_PROMPT}:"
        f"{GEMINI_TTS_CONTINUITY_PROMPT}:"
        f"{edge_voice}"
    )


def _provider_chain(provider_chain: list[str] | None = None) -> list[str]:
    providers = list(provider_chain or TTS_PROVIDER_CHAIN)

    if not providers:
        providers = [TTS_PROVIDER]

        if TTS_PROVIDER == "gemini":
            providers.append("edge")

    normalized_providers: list[str] = []

    for provider in providers:
        provider = provider.strip().lower()

        if provider not in TTS_PROVIDER_NAMES:
            continue

        if provider not in normalized_providers:
            normalized_providers.append(provider)

    return normalized_providers or ["edge"]


def _chunk_max_length_for_providers(providers: list[str]) -> int:
    specs = _provider_specs()
    limits = [
        specs[provider].chunk_max_length
        for provider in providers
        if provider in specs
    ]

    return min(limits) if limits else DEFAULT_TTS_CHUNK_MAX_LENGTH


async def _notify_progress(
    progress_callback: TTSProgressCallback | None,
    completed_chunks: int,
    chunks_count: int,
    provider: str,
    cache_hit: bool,
) -> None:
    if progress_callback is None:
        return

    try:
        await progress_callback(
            completed_chunks,
            chunks_count,
            provider,
            cache_hit,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("TTS: progress callback failed")


def _cache_voice_for_provider(provider: str, voice: str) -> str:
    return _provider_spec(provider).cache_voice_name(voice)


def _validate_tts_input(text: str, voice: str, rate: str) -> None:
    """
    Базова перевірка вхідних даних для TTS.
    """
    if not text or not text.strip():
        raise ValueError("TTS text порожній.")

    if not voice or not voice.strip():
        raise ValueError("TTS voice порожній.")

    if rate is None:
        raise ValueError("TTS rate не заданий.")


async def _save_edge_tts_to_mp3(
    text: str,
    voice: str,
    rate: str,
    mp3_path: str,
) -> None:
    """
    Генерує mp3 через edge-tts.
    """
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
    )

    try:
        await asyncio.wait_for(
            communicate.save(mp3_path),
            timeout=EDGE_TTS_REQUEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as error:
        raise RuntimeError(
            "Edge TTS timeout: request took longer than "
            f"{EDGE_TTS_REQUEST_TIMEOUT_SECONDS} seconds."
        ) from error

    if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
        raise RuntimeError("Edge TTS не створив коректний mp3-файл.")


async def _generate_chunk_voice(
    chunk: str,
    voice: str,
    rate: str,
    chunk_index: int,
    chunks_count: int,
) -> str:
    """
    Генерує один OGG-файл для одного текстового фрагмента.

    Якщо Edge TTS або ffmpeg тимчасово впали,
    робить кілька повторних спроб.
    """
    last_error: Exception | None = None

    for attempt in range(1, TTS_RETRY_ATTEMPTS + 1):
        mp3_path = create_temp_file_path(".mp3")

        try:
            logger.info(
                "TTS: генерація chunk=%s/%s, attempt=%s/%s, text_length=%s",
                chunk_index,
                chunks_count,
                attempt,
                TTS_RETRY_ATTEMPTS,
                len(chunk),
            )

            await _save_edge_tts_to_mp3(
                text=chunk,
                voice=voice,
                rate=rate,
                mp3_path=mp3_path,
            )

            ogg_path = await convert_to_ogg(mp3_path)

            logger.info(
                "TTS: chunk=%s/%s успішно згенеровано",
                chunk_index,
                chunks_count,
            )

            return ogg_path

        except asyncio.CancelledError:
            raise

        except Exception as error:
            last_error = error

            logger.exception(
                "TTS: помилка chunk=%s/%s, attempt=%s/%s",
                chunk_index,
                chunks_count,
                attempt,
                TTS_RETRY_ATTEMPTS,
            )

            if attempt < TTS_RETRY_ATTEMPTS:
                await asyncio.sleep(TTS_RETRY_BASE_DELAY_SECONDS * attempt)

        finally:
            safe_remove_file(mp3_path)

    raise RuntimeError(
        f"TTS не вдалося згенерувати chunk {chunk_index}/{chunks_count}: {last_error}"
    )


async def _generate_gemini_chunk_voice(
    *,
    chunk: str,
    voice: str,
    rate: str,
    chunk_index: int,
    chunks_count: int,
) -> str:
    return await generate_gemini_tts_ogg(
        text=chunk,
        voice=voice,
        rate=rate,
        chunk_index=chunk_index,
        chunks_count=chunks_count,
    )


async def _generate_edge_chunk_voice(
    *,
    chunk: str,
    voice: str,
    rate: str,
    chunk_index: int,
    chunks_count: int,
) -> str:
    return await _generate_chunk_voice(
        chunk=chunk,
        voice=voice,
        rate=rate,
        chunk_index=chunk_index,
        chunks_count=chunks_count,
    )


def _provider_specs() -> dict[str, TTSProviderSpec]:
    return {
        "edge": TTSProviderSpec(
            chunk_max_length=DEFAULT_TTS_CHUNK_MAX_LENGTH,
            cache_voice_name=lambda voice: voice,
            generate_chunk=_generate_edge_chunk_voice,
            record_local_metrics=True,
        ),
        "gemini": TTSProviderSpec(
            chunk_max_length=GEMINI_TTS_CHUNK_MAX_LENGTH,
            cache_voice_name=_gemini_cache_voice_name,
            generate_chunk=_generate_gemini_chunk_voice,
            record_local_metrics=False,
        ),
    }


def _provider_spec(provider: str) -> TTSProviderSpec:
    spec = _provider_specs().get(provider)

    if spec is None:
        raise RuntimeError(f"Unknown TTS provider: {provider}")

    return spec


async def _generate_chunk_voice_with_provider(
    *,
    provider: str,
    chunk: str,
    voice: str,
    rate: str,
    chunk_index: int,
    chunks_count: int,
) -> str:
    return await _provider_spec(provider).generate_chunk(
        chunk=chunk,
        voice=voice,
        rate=rate,
        chunk_index=chunk_index,
        chunks_count=chunks_count,
    )


async def _generate_chunk_voice_for_provider(
    *,
    chunk: str,
    voice: str,
    rate: str,
    chunk_index: int,
    chunks_count: int,
    provider_chain: list[str] | None = None,
    user_id: int | None = None,
) -> tuple[str, str, bool, str]:
    providers = _provider_chain(provider_chain)
    provider_errors: list[str] = []

    for provider in providers:
        provider_spec = _provider_spec(provider)
        cache_voice = _cache_voice_for_provider(provider, voice)
        cache_lookup_kwargs = {
            "text": chunk,
            "voice": cache_voice,
            "rate": rate,
        }

        if user_id is not None:
            cache_lookup_kwargs["user_id"] = user_id

        cached_audio_path = get_audio_from_cache(**cache_lookup_kwargs)

        if cached_audio_path:
            logger.info(
                "TTS: cache hit provider=%s chunk=%s/%s",
                provider,
                chunk_index,
                chunks_count,
            )
            return cached_audio_path, cache_voice, True, provider

        started_at = time.perf_counter()

        try:
            ogg_path = await _generate_chunk_voice_with_provider(
                provider=provider,
                chunk=chunk,
                voice=voice,
                rate=rate,
                chunk_index=chunk_index,
                chunks_count=chunks_count,
            )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)

            if provider_spec.record_local_metrics:
                await record_service_metric(
                    provider=provider,
                    operation="tts",
                    success=True,
                    latency_ms=elapsed_ms,
                    input_units=len(chunk),
                )

            return ogg_path, cache_voice, False, provider

        except asyncio.CancelledError:
            raise

        except Exception as error:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)

            if provider_spec.record_local_metrics:
                await record_service_metric(
                    provider=provider,
                    operation="tts",
                    success=False,
                    latency_ms=elapsed_ms,
                    input_units=len(chunk),
                    error=error,
                )

            provider_errors.append(f"{provider}: {error}")

            if _is_expected_provider_failure(error):
                logger.warning(
                    "TTS: provider=%s skipped by quota, chunk=%s/%s, fallback continues",
                    provider,
                    chunk_index,
                    chunks_count,
                )
            else:
                logger.exception(
                    "TTS: provider=%s впав, chunk=%s/%s",
                    provider,
                    chunk_index,
                    chunks_count,
                )

    details = "; ".join(provider_errors) or "no providers configured"
    raise RuntimeError(
        f"TTS не вдалося згенерувати chunk {chunk_index}/{chunks_count}: {details}"
    )


async def generate_voice(
    text: str,
    voice: str,
    rate: str,
    raise_on_error: bool = False,
    provider_chain: list[str] | None = None,
    progress_callback: TTSProgressCallback | None = None,
    user_id: int | None = None,
) -> list[str]:
    """
    Генерує voice-файли для Telegram.

    Повертає список шляхів до .ogg файлів.

    Важлива поведінка:
    - якщо все добре — повертає список файлів;
    - якщо сталася помилка — видаляє вже створені файли;
    - за замовчуванням повертає [], щоб не ламати старі handlers;
    - якщо raise_on_error=True — піднімає помилку вище.
    """
    generated_files: list[str] = []

    try:
        _validate_tts_input(text, voice, rate)

        providers = _provider_chain(provider_chain)
        chunk_max_length = _chunk_max_length_for_providers(providers)
        chunks = split_text(text, max_length=chunk_max_length)
        chunks = [chunk.strip() for chunk in chunks if chunk and chunk.strip()]

        if not chunks:
            logger.warning("TTS: split_text повернув порожній список.")
            return []

        logger.info(
            "TTS: старт генерації, chunks=%s, voice=%s, rate=%s, providers=%s",
            len(chunks),
            voice,
            rate,
            ",".join(providers),
        )

        for index, chunk in enumerate(chunks, start=1):
            async with tts_semaphore:
                (
                    ogg_path,
                    cache_voice,
                    cache_hit,
                    used_provider,
                ) = await _generate_chunk_voice_for_provider(
                    chunk=chunk,
                    voice=voice,
                    rate=rate,
                    chunk_index=index,
                    chunks_count=len(chunks),
                    provider_chain=providers,
                    user_id=user_id,
                )

            if not cache_hit:
                cache_save_kwargs = {
                    "text": chunk,
                    "voice": cache_voice,
                    "rate": rate,
                    "audio_path": ogg_path,
                }

                if user_id is not None:
                    cache_save_kwargs["user_id"] = user_id

                save_audio_to_cache(**cache_save_kwargs)

            generated_files.append(ogg_path)
            await _notify_progress(
                progress_callback,
                index,
                len(chunks),
                used_provider,
                cache_hit,
            )

        logger.info(
            "TTS: генерацію завершено, files=%s",
            len(generated_files),
        )

        return generated_files

    except asyncio.CancelledError:
        logger.info("TTS: генерацію скасовано.")
        for file_path in generated_files:
            safe_remove_file(file_path)
        raise

    except Exception as error:
        logger.exception("TTS: генерація завершилась помилкою: %s", error)

        for file_path in generated_files:
            safe_remove_file(file_path)

        if raise_on_error:
            raise

        return []
