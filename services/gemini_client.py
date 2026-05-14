# Файл: services/gemini_client.py

import asyncio
import logging
import time
from typing import Any

from google import genai

from config import (
    GEMINI_API_KEY,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    GEMINI_RETRY_ATTEMPTS,
    GEMINI_RETRY_BASE_DELAY_SECONDS,
    GEMINI_RETRY_MAX_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)

_gemini_client: genai.Client | None = None


def _get_gemini_client() -> genai.Client:
    global _gemini_client

    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    return _gemini_client


def _retry_delay(attempt: int) -> float:
    delay = GEMINI_RETRY_BASE_DELAY_SECONDS * (2 ** max(attempt - 1, 0))
    return min(delay, GEMINI_RETRY_MAX_DELAY_SECONDS)


async def generate_gemini_content(
    *,
    model: str,
    contents: Any,
    config: Any | None = None,
    context: str,
) -> Any:
    """
    Calls Gemini with a bounded timeout and small retry budget.
    """
    attempts = max(GEMINI_RETRY_ATTEMPTS, 1)
    last_error: Exception | None = None

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
                timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
            )

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "Gemini: context=%s model=%s attempt=%s/%s elapsed_ms=%s",
                context,
                model,
                attempt,
                attempts,
                elapsed_ms,
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

            if attempt >= attempts:
                break

            await asyncio.sleep(_retry_delay(attempt))

    raise RuntimeError(
        f"Gemini request failed context={context} model={model}"
    ) from last_error
