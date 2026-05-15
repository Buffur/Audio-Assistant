from types import SimpleNamespace

import pytest

from services import gemini_client


class FakeGeminiModels:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)

        if isinstance(result, Exception):
            raise result

        return result


def _fake_client(models):
    return SimpleNamespace(
        aio=SimpleNamespace(
            models=models,
        )
    )


@pytest.mark.asyncio
async def test_generate_gemini_content_retries_after_failure(monkeypatch) -> None:
    models = FakeGeminiModels(
        [
            RuntimeError("temporary failure"),
            SimpleNamespace(text="ok"),
        ]
    )
    metrics = []

    async def fake_record_service_metric(**kwargs):
        metrics.append(kwargs)

    monkeypatch.setattr(gemini_client, "_get_gemini_client", lambda: _fake_client(models))
    monkeypatch.setattr(gemini_client, "record_service_metric", fake_record_service_metric)
    monkeypatch.setattr(gemini_client, "GEMINI_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(gemini_client, "GEMINI_RETRY_BASE_DELAY_SECONDS", 0.001)
    monkeypatch.setattr(gemini_client, "GEMINI_RETRY_MAX_DELAY_SECONDS", 0.001)
    monkeypatch.setattr(gemini_client, "GEMINI_REQUEST_TIMEOUT_SECONDS", 1)

    response = await gemini_client.generate_gemini_content(
        model="gemini-test",
        contents="prompt",
        config=SimpleNamespace(temperature=0.1),
        context="test",
    )

    assert response.text == "ok"
    assert len(models.calls) == 2
    assert models.calls[0]["model"] == "gemini-test"
    assert models.calls[0]["contents"] == "prompt"
    assert [metric["success"] for metric in metrics] == [False, True]
    assert metrics[-1]["provider"] == "gemini"
    assert metrics[-1]["operation"] == "test"
    assert metrics[-1]["input_units"] == len("prompt")
    assert metrics[-1]["output_units"] == len("ok")


@pytest.mark.asyncio
async def test_generate_gemini_content_uses_timeout_override(monkeypatch) -> None:
    models = FakeGeminiModels([SimpleNamespace(text="ok")])
    captured = {}

    async def fake_record_service_metric(**kwargs):
        return None

    async def fake_wait_for(awaitable, timeout):
        captured["timeout"] = timeout
        return await awaitable

    monkeypatch.setattr(gemini_client, "_get_gemini_client", lambda: _fake_client(models))
    monkeypatch.setattr(gemini_client, "record_service_metric", fake_record_service_metric)
    monkeypatch.setattr(gemini_client.asyncio, "wait_for", fake_wait_for)

    response = await gemini_client.generate_gemini_content(
        model="gemini-test",
        contents="prompt",
        context="tts",
        timeout_seconds=123,
    )

    assert response.text == "ok"
    assert captured["timeout"] == 123


@pytest.mark.asyncio
async def test_generate_gemini_content_raises_after_retry_budget(monkeypatch) -> None:
    models = FakeGeminiModels(
        [
            RuntimeError("first failure"),
            RuntimeError("second failure"),
        ]
    )
    metrics = []

    async def fake_record_service_metric(**kwargs):
        metrics.append(kwargs)

    monkeypatch.setattr(gemini_client, "_get_gemini_client", lambda: _fake_client(models))
    monkeypatch.setattr(gemini_client, "record_service_metric", fake_record_service_metric)
    monkeypatch.setattr(gemini_client, "GEMINI_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(gemini_client, "GEMINI_RETRY_BASE_DELAY_SECONDS", 0.001)
    monkeypatch.setattr(gemini_client, "GEMINI_RETRY_MAX_DELAY_SECONDS", 0.001)
    monkeypatch.setattr(gemini_client, "GEMINI_REQUEST_TIMEOUT_SECONDS", 1)

    with pytest.raises(RuntimeError, match="Gemini request failed"):
        await gemini_client.generate_gemini_content(
            model="gemini-test",
            contents="prompt",
            context="test",
        )

    assert len(models.calls) == 2
    assert [metric["success"] for metric in metrics] == [False, False]
    assert metrics[-1]["error"].args == ("second failure",)


@pytest.mark.asyncio
async def test_generate_gemini_content_does_not_retry_quota_errors(monkeypatch) -> None:
    quota_error = RuntimeError("429 RESOURCE_EXHAUSTED. Quota exceeded.")
    models = FakeGeminiModels([quota_error, SimpleNamespace(text="unused")])
    metrics = []

    async def fake_record_service_metric(**kwargs):
        metrics.append(kwargs)

    monkeypatch.setattr(gemini_client, "_get_gemini_client", lambda: _fake_client(models))
    monkeypatch.setattr(gemini_client, "record_service_metric", fake_record_service_metric)
    monkeypatch.setattr(gemini_client, "GEMINI_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(gemini_client, "GEMINI_REQUEST_TIMEOUT_SECONDS", 1)

    with pytest.raises(gemini_client.GeminiQuotaExceededError):
        await gemini_client.generate_gemini_content(
            model="gemini-test",
            contents="prompt",
            context="tts",
        )

    assert len(models.calls) == 1
    assert len(metrics) == 1
    assert metrics[0]["success"] is False


@pytest.mark.asyncio
async def test_generate_gemini_content_does_not_retry_model_errors(monkeypatch) -> None:
    model_error = RuntimeError(
        "404 models/gemini-old is not found for API version v1beta"
    )
    models = FakeGeminiModels([model_error, SimpleNamespace(text="unused")])
    metrics = []

    async def fake_record_service_metric(**kwargs):
        metrics.append(kwargs)

    monkeypatch.setattr(gemini_client, "_get_gemini_client", lambda: _fake_client(models))
    monkeypatch.setattr(gemini_client, "record_service_metric", fake_record_service_metric)
    monkeypatch.setattr(gemini_client, "GEMINI_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(gemini_client, "GEMINI_REQUEST_TIMEOUT_SECONDS", 1)

    with pytest.raises(gemini_client.GeminiModelUnavailableError):
        await gemini_client.generate_gemini_content(
            model="gemini-old",
            contents="prompt",
            context="parser",
        )

    assert len(models.calls) == 1
    assert len(metrics) == 1
    assert metrics[0]["success"] is False


@pytest.mark.asyncio
async def test_generate_gemini_content_with_fallback_tries_next_model_on_quota(
    monkeypatch,
) -> None:
    models = FakeGeminiModels(
        [
            RuntimeError("429 RESOURCE_EXHAUSTED. Quota exceeded."),
            SimpleNamespace(text="ok"),
        ]
    )

    async def fake_record_service_metric(**kwargs):
        return None

    monkeypatch.setattr(gemini_client, "_get_gemini_client", lambda: _fake_client(models))
    monkeypatch.setattr(gemini_client, "record_service_metric", fake_record_service_metric)
    monkeypatch.setattr(gemini_client, "GEMINI_REQUEST_TIMEOUT_SECONDS", 1)

    response = await gemini_client.generate_gemini_content_with_fallback(
        primary_model="gemini-primary",
        fallback_models=["gemini-fallback"],
        contents="prompt",
        context="parser",
    )

    assert response.text == "ok"
    assert [call["model"] for call in models.calls] == [
        "gemini-primary",
        "gemini-fallback",
    ]


@pytest.mark.asyncio
async def test_generate_gemini_content_with_fallback_tries_next_model_on_model_error(
    monkeypatch,
) -> None:
    models = FakeGeminiModels(
        [
            RuntimeError("model has been deprecated"),
            SimpleNamespace(text="ok"),
        ]
    )

    async def fake_record_service_metric(**kwargs):
        return None

    monkeypatch.setattr(gemini_client, "_get_gemini_client", lambda: _fake_client(models))
    monkeypatch.setattr(gemini_client, "record_service_metric", fake_record_service_metric)
    monkeypatch.setattr(gemini_client, "GEMINI_REQUEST_TIMEOUT_SECONDS", 1)

    response = await gemini_client.generate_gemini_content_with_fallback(
        primary_model="gemini-old",
        fallback_models=["gemini-new"],
        contents="prompt",
        context="ocr",
    )

    assert response.text == "ok"
    assert [call["model"] for call in models.calls] == [
        "gemini-old",
        "gemini-new",
    ]


@pytest.mark.asyncio
async def test_generate_gemini_content_with_fallback_raises_expected_error_when_exhausted(
    monkeypatch,
) -> None:
    models = FakeGeminiModels(
        [
            RuntimeError("model has been deprecated"),
            RuntimeError("429 RESOURCE_EXHAUSTED. Quota exceeded."),
        ]
    )

    async def fake_record_service_metric(**kwargs):
        return None

    monkeypatch.setattr(gemini_client, "_get_gemini_client", lambda: _fake_client(models))
    monkeypatch.setattr(gemini_client, "record_service_metric", fake_record_service_metric)
    monkeypatch.setattr(gemini_client, "GEMINI_REQUEST_TIMEOUT_SECONDS", 1)

    with pytest.raises(gemini_client.GeminiFallbackExhaustedError):
        await gemini_client.generate_gemini_content_with_fallback(
            primary_model="gemini-old",
            fallback_models=["gemini-over-quota"],
            contents="prompt",
            context="tts",
        )
