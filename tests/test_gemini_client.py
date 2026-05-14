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

    monkeypatch.setattr(gemini_client, "_get_gemini_client", lambda: _fake_client(models))
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


@pytest.mark.asyncio
async def test_generate_gemini_content_raises_after_retry_budget(monkeypatch) -> None:
    models = FakeGeminiModels(
        [
            RuntimeError("first failure"),
            RuntimeError("second failure"),
        ]
    )

    monkeypatch.setattr(gemini_client, "_get_gemini_client", lambda: _fake_client(models))
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
