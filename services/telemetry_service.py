import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from config import (
    GEMINI_ESTIMATED_INPUT_COST_PER_1K_CHARS_USD,
    GEMINI_ESTIMATED_OUTPUT_COST_PER_1K_CHARS_USD,
    TTS_ESTIMATED_COST_PER_1K_CHARS_USD,
)
from database.db import add_service_metric

logger = logging.getLogger(__name__)

TELEMETRY_QUEUE_MAX_SIZE = 1000
TELEMETRY_FLUSH_TIMEOUT_SECONDS = 5.0

_telemetry_queue: asyncio.Queue[dict[str, Any]] | None = None
_telemetry_worker_task: asyncio.Task | None = None


def estimate_payload_units(payload: Any) -> int:
    if payload is None:
        return 0

    if isinstance(payload, str):
        return len(payload)

    if isinstance(payload, bytes | bytearray):
        return len(payload)

    if isinstance(payload, Mapping):
        return sum(estimate_payload_units(value) for value in payload.values())

    if isinstance(payload, Sequence) and not isinstance(payload, str):
        return sum(estimate_payload_units(item) for item in payload)

    text = getattr(payload, "text", None)

    if isinstance(text, str):
        return len(text)

    inline_data = getattr(payload, "inline_data", None)

    if inline_data is not None:
        data = getattr(inline_data, "data", None)

        if isinstance(data, bytes | bytearray):
            return len(data)

    parts = getattr(payload, "parts", None)

    if parts is not None:
        return estimate_payload_units(parts)

    return 0


def estimate_response_units(response: Any) -> int:
    text = getattr(response, "text", None)

    if isinstance(text, str):
        return len(text)

    return 0


def estimate_service_cost_usd(
    provider: str,
    operation: str,
    input_units: int,
    output_units: int = 0,
) -> float:
    provider = provider.strip().lower()

    if provider == "gemini":
        return (
            input_units * GEMINI_ESTIMATED_INPUT_COST_PER_1K_CHARS_USD / 1000
            + output_units * GEMINI_ESTIMATED_OUTPUT_COST_PER_1K_CHARS_USD / 1000
        )

    if operation == "tts":
        return input_units * TTS_ESTIMATED_COST_PER_1K_CHARS_USD / 1000

    return 0.0


async def _write_service_metric(metric: dict[str, Any]) -> None:
    await add_service_metric(**metric)


async def _telemetry_worker(queue: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        metric = await queue.get()

        try:
            await _write_service_metric(metric)

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Telemetry: failed to write service metric provider=%s operation=%s",
                metric.get("provider"),
                metric.get("operation"),
            )

        finally:
            queue.task_done()


def _ensure_telemetry_worker() -> asyncio.Queue[dict[str, Any]]:
    global _telemetry_queue, _telemetry_worker_task

    if _telemetry_queue is None:
        _telemetry_queue = asyncio.Queue(maxsize=TELEMETRY_QUEUE_MAX_SIZE)

    if _telemetry_worker_task is None or _telemetry_worker_task.done():
        _telemetry_worker_task = asyncio.create_task(
            _telemetry_worker(_telemetry_queue)
        )

    return _telemetry_queue


async def record_service_metric(
    *,
    provider: str,
    operation: str,
    success: bool,
    latency_ms: int,
    input_units: int = 0,
    output_units: int = 0,
    estimated_cost_usd: float | None = None,
    error: Exception | None = None,
) -> None:
    if estimated_cost_usd is None:
        estimated_cost_usd = estimate_service_cost_usd(
            provider=provider,
            operation=operation,
            input_units=input_units,
            output_units=output_units,
        )

    metric = {
        "provider": provider,
        "operation": operation,
        "success": success,
        "latency_ms": latency_ms,
        "input_units": input_units,
        "output_units": output_units,
        "estimated_cost_usd": estimated_cost_usd,
        "error_type": type(error).__name__ if error else None,
        "error_message": str(error) if error else None,
    }

    try:
        queue = _ensure_telemetry_worker()
        queue.put_nowait(metric)

    except asyncio.QueueFull:
        logger.warning(
            "Telemetry: queue full, dropping metric provider=%s operation=%s",
            provider,
            operation,
        )

    except Exception:
        logger.exception(
            "Telemetry: failed to enqueue service metric provider=%s operation=%s",
            provider,
            operation,
        )


async def flush_telemetry_metrics(
    timeout_seconds: float | None = TELEMETRY_FLUSH_TIMEOUT_SECONDS,
) -> None:
    global _telemetry_worker_task

    queue = _telemetry_queue

    if queue is None:
        return

    if _telemetry_worker_task is None or _telemetry_worker_task.done():
        _telemetry_worker_task = asyncio.create_task(_telemetry_worker(queue))

    try:
        if timeout_seconds is None:
            await queue.join()
            return

        await asyncio.wait_for(queue.join(), timeout=timeout_seconds)

    except asyncio.TimeoutError:
        logger.warning(
            "Telemetry: flush timed out with pending_metrics=%s",
            queue.qsize(),
        )


async def close_telemetry_service(
    timeout_seconds: float | None = TELEMETRY_FLUSH_TIMEOUT_SECONDS,
) -> None:
    global _telemetry_queue, _telemetry_worker_task

    await flush_telemetry_metrics(timeout_seconds=timeout_seconds)

    task = _telemetry_worker_task
    _telemetry_worker_task = None
    _telemetry_queue = None

    if task is None or task.done():
        return

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass
