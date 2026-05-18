import asyncio

import pytest

from services import telemetry_service


@pytest.mark.asyncio
async def test_record_service_metric_enqueues_and_flushes(monkeypatch) -> None:
    await telemetry_service.close_telemetry_service(timeout_seconds=0.1)

    writes = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_add_service_metric(**kwargs):
        started.set()
        await release.wait()
        writes.append(kwargs)

    monkeypatch.setattr(
        telemetry_service,
        "add_service_metric",
        fake_add_service_metric,
    )

    try:
        await telemetry_service.record_service_metric(
            provider="edge",
            operation="tts",
            success=True,
            latency_ms=25,
            input_units=100,
        )

        await asyncio.wait_for(started.wait(), timeout=1)
        assert writes == []

        release.set()
        await telemetry_service.flush_telemetry_metrics(timeout_seconds=1)

        assert writes == [
            {
                "provider": "edge",
                "operation": "tts",
                "success": True,
                "latency_ms": 25,
                "input_units": 100,
                "output_units": 0,
                "estimated_cost_usd": 0.0,
                "error_type": None,
                "error_message": None,
            }
        ]

    finally:
        release.set()
        await telemetry_service.close_telemetry_service(timeout_seconds=1)


@pytest.mark.asyncio
async def test_record_service_metric_survives_write_failure(monkeypatch) -> None:
    await telemetry_service.close_telemetry_service(timeout_seconds=0.1)

    calls = 0

    async def fake_add_service_metric(**kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("database is busy")

    monkeypatch.setattr(
        telemetry_service,
        "add_service_metric",
        fake_add_service_metric,
    )

    try:
        await telemetry_service.record_service_metric(
            provider="gemini",
            operation="ocr",
            success=False,
            latency_ms=100,
            error=RuntimeError("Gemini failed"),
        )

        await telemetry_service.flush_telemetry_metrics(timeout_seconds=1)
        assert calls == 1

    finally:
        await telemetry_service.close_telemetry_service(timeout_seconds=1)


@pytest.mark.asyncio
async def test_record_service_metric_publishes_external_after_sqlite_failure(
    monkeypatch,
) -> None:
    await telemetry_service.close_telemetry_service(timeout_seconds=0.1)

    external_metrics = []

    async def fake_add_service_metric(**kwargs):
        raise RuntimeError("sqlite unavailable")

    async def fake_publish_external_metric(metric):
        external_metrics.append(metric)

    monkeypatch.setattr(
        telemetry_service,
        "add_service_metric",
        fake_add_service_metric,
    )
    monkeypatch.setattr(
        telemetry_service,
        "_publish_external_metric",
        fake_publish_external_metric,
    )

    try:
        await telemetry_service.record_service_metric(
            provider="gemini",
            operation="tts",
            success=False,
            latency_ms=250,
            error=RuntimeError("provider failed"),
        )

        await telemetry_service.flush_telemetry_metrics(timeout_seconds=1)

        assert len(external_metrics) == 1
        assert external_metrics[0]["provider"] == "gemini"
        assert external_metrics[0]["success"] is False

    finally:
        await telemetry_service.close_telemetry_service(timeout_seconds=1)
