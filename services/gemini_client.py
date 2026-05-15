# Файл: services/gemini_client.py

import asyncio
import logging
import time
from contextlib import suppress
from typing import Any

from google import genai

from config import (
    GEMINI_API_KEY,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    GEMINI_RETRY_ATTEMPTS,
    GEMINI_RETRY_BASE_DELAY_SECONDS,
    GEMINI_RETRY_MAX_DELAY_SECONDS,
)
from services.telemetry_service import (
    estimate_payload_units,
    estimate_response_units,
    record_service_metric,
)

logger = logging.getLogger(__name__)

_gemini_client: genai.Client | None = None


class GeminiQuotaExceededError(RuntimeError):
    pass


class GeminiModelUnavailableError(RuntimeError):
    pass


class GeminiFallbackExhaustedError(RuntimeError):
    pass


def _get_gemini_client() -> genai.Client:
    global _gemini_client

    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    return _gemini_client


def _retry_delay(attempt: int) -> float:
    delay = GEMINI_RETRY_BASE_DELAY_SECONDS * (2 ** max(attempt - 1, 0))
    return min(delay, GEMINI_RETRY_MAX_DELAY_SECONDS)


def _error_status_code(error: Exception) -> int | None:
    raw_status_code = (
        getattr(error, "code", None)
        or getattr(error, "status_code", None)
    )

    if callable(raw_status_code):
        with suppress(Exception):
            raw_status_code = raw_status_code()

    try:
        return int(raw_status_code)
    except (TypeError, ValueError):
        return None


def _is_quota_error(error: Exception) -> bool:
    if _error_status_code(error) == 429:
        return True

    error_text = str(error).lower()

    return "resource_exhausted" in error_text or "quota exceeded" in error_text


def _is_model_unavailable_error(error: Exception) -> bool:
    status_code = _error_status_code(error)
    error_text = str(error).lower()

    if status_code == 404:
        return True

    model_markers = [
        "model not found",
        "models/",
        "not found for api version",
        "is not found",
        "not supported for generatecontent",
        "unsupported model",
        "model is not supported",
        "deprecated model",
        "model has been deprecated",
    ]

    if any(marker in error_text for marker in model_markers):
        return True

    return (
        "model" in error_text
        and any(
            marker in error_text
            for marker in [
                "not available",
                "unavailable",
                "retired",
                "deprecated",
            ]
        )
    )


def normalize_model_chain(
    primary_model: str,
    fallback_models: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    models = [primary_model, *(fallback_models or [])]
    normalized_models: list[str] = []

    for model in models:
        model = str(model).strip()

        if not model:
            continue

        if model not in normalized_models:
            normalized_models.append(model)

    return normalized_models


async def generate_gemini_content(
    *,
    model: str,
    contents: Any,
    config: Any | None = None,
    context: str,
    timeout_seconds: int | float | None = None,
) -> Any:
    """
    Calls Gemini with a bounded timeout and small retry budget.
    """
    attempts = max(GEMINI_RETRY_ATTEMPTS, 1)
    last_error: Exception | None = None
    input_units = estimate_payload_units(contents)
    request_timeout_seconds = timeout_seconds or GEMINI_REQUEST_TIMEOUT_SECONDS

    for attempt in range(1, attempts + 1):
        started_at = time.perf_counter()

        try:
            client = _get_gemini_client()
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                ),
                timeout=request_timeout_seconds,
            )

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            output_units = estimate_response_units(response)
            logger.info(
                "Gemini: context=%s model=%s attempt=%s/%s elapsed_ms=%s",
                context,
                model,
                attempt,
                attempts,
                elapsed_ms,
            )
            await record_service_metric(
                provider="gemini",
                operation=context,
                success=True,
                latency_ms=elapsed_ms,
                input_units=input_units,
                output_units=output_units,
            )
            return response

        except Exception as error:
            last_error = error
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)

            logger.warning(
                "Gemini: context=%s model=%s attempt=%s/%s failed elapsed_ms=%s error=%s",
                context,
                model,
                attempt,
                attempts,
                elapsed_ms,
                error,
            )
            await record_service_metric(
                provider="gemini",
                operation=context,
                success=False,
                latency_ms=elapsed_ms,
                input_units=input_units,
                error=error,
            )

            if _is_quota_error(error):
                raise GeminiQuotaExceededError(
                    f"Gemini quota exhausted context={context} model={model}"
                ) from error

            if _is_model_unavailable_error(error):
                raise GeminiModelUnavailableError(
                    f"Gemini model unavailable context={context} model={model}"
                ) from error

            if attempt >= attempts:
                break

            await asyncio.sleep(_retry_delay(attempt))

    raise RuntimeError(
        f"Gemini request failed context={context} model={model}"
    ) from last_error


async def generate_gemini_content_with_fallback(
    *,
    primary_model: str,
    fallback_models: list[str] | tuple[str, ...] | None = None,
    contents: Any,
    config: Any | None = None,
    context: str,
    timeout_seconds: int | float | None = None,
) -> Any:
    model_chain = normalize_model_chain(
        primary_model=primary_model,
        fallback_models=fallback_models,
    )
    last_fallback_error: Exception | None = None

    for model in model_chain:
        try:
            return await generate_gemini_content(
                model=model,
                contents=contents,
                config=config,
                context=context,
                timeout_seconds=timeout_seconds,
            )
        except (
            GeminiQuotaExceededError,
            GeminiModelUnavailableError,
        ) as error:
            last_fallback_error = error
            logger.warning(
                "Gemini: context=%s model=%s fallback reason=%s, trying next model",
                context,
                model,
                type(error).__name__,
            )

    raise GeminiFallbackExhaustedError(
        f"Gemini fallback exhausted for all models context={context}: "
        f"{', '.join(model_chain)}"
    ) from last_fallback_error
