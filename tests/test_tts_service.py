import pytest

from services import tts


@pytest.fixture(autouse=True)
def use_default_edge_provider(monkeypatch) -> None:
    async def fake_record_service_metric(**kwargs):
        return None

    monkeypatch.setattr(tts, "TTS_PROVIDER", "edge")
    monkeypatch.setattr(tts, "TTS_PROVIDER_CHAIN", [])
    monkeypatch.setattr(tts, "record_service_metric", fake_record_service_metric)


def test_validate_tts_input_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        tts._validate_tts_input("", "voice", "+0%")

    with pytest.raises(ValueError):
        tts._validate_tts_input("text", "", "+0%")

    with pytest.raises(ValueError):
        tts._validate_tts_input("text", "voice", None)


def test_tts_provider_specs_cover_supported_provider_names() -> None:
    assert set(tts._provider_specs()) == tts.TTS_PROVIDER_NAMES
    assert tts._provider_spec("edge").record_local_metrics is True
    assert tts._provider_spec("gemini").record_local_metrics is False


def test_tts_provider_chain_deduplicates_and_ignores_unknown_provider() -> None:
    assert tts._provider_chain(["gemini", "edge", "gemini", "unknown"]) == [
        "gemini",
        "edge",
    ]


@pytest.mark.asyncio
async def test_edge_tts_save_uses_configured_timeout(monkeypatch, tmp_path) -> None:
    captured = {}

    class FakeCommunicate:
        def __init__(self, text: str, voice: str, rate: str) -> None:
            captured["communicate"] = {
                "text": text,
                "voice": voice,
                "rate": rate,
            }

        async def save(self, mp3_path: str) -> None:
            captured["mp3_path"] = mp3_path
            with open(mp3_path, "wb") as file:
                file.write(b"mp3")

    async def fake_wait_for(awaitable, timeout):
        captured["timeout"] = timeout
        return await awaitable

    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.setattr(tts.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(tts, "EDGE_TTS_REQUEST_TIMEOUT_SECONDS", 12)

    mp3_path = tmp_path / "voice.mp3"

    await tts._save_edge_tts_to_mp3(
        text="hello",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        mp3_path=str(mp3_path),
    )

    assert captured["communicate"] == {
        "text": "hello",
        "voice": "uk-UA-PolinaNeural",
        "rate": "+0%",
    }
    assert captured["mp3_path"] == str(mp3_path)
    assert captured["timeout"] == 12


@pytest.mark.asyncio
async def test_edge_tts_save_raises_runtime_error_on_timeout(
    monkeypatch,
    tmp_path,
) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, voice: str, rate: str) -> None:
            return None

        async def save(self, mp3_path: str) -> None:
            return None

    async def fake_wait_for(awaitable, timeout):
        awaitable.close()
        raise tts.asyncio.TimeoutError

    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.setattr(tts.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(tts, "EDGE_TTS_REQUEST_TIMEOUT_SECONDS", 12)

    with pytest.raises(RuntimeError, match="Edge TTS timeout"):
        await tts._save_edge_tts_to_mp3(
            text="hello",
            voice="uk-UA-PolinaNeural",
            rate="+0%",
            mp3_path=str(tmp_path / "voice.mp3"),
        )


@pytest.mark.asyncio
async def test_generate_voice_uses_split_chunks(monkeypatch) -> None:
    async def fake_generate_chunk_voice(
        chunk,
        voice,
        rate,
        chunk_index,
        chunks_count,
    ):
        return f"/tmp/{chunk_index}-{chunks_count}-{chunk}.ogg"

    monkeypatch.setattr(
        tts,
        "split_text",
        lambda text, max_length=None: ["one", "two"],
    )
    monkeypatch.setattr(tts, "_generate_chunk_voice", fake_generate_chunk_voice)

    result = await tts.generate_voice(
        text="one two",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
    )

    assert result == ["/tmp/1-2-one.ogg", "/tmp/2-2-two.ogg"]


@pytest.mark.asyncio
async def test_generate_voice_uses_cached_audio(monkeypatch) -> None:
    async def fail_generate_chunk_voice(*args, **kwargs):
        raise AssertionError("_generate_chunk_voice should not be called")

    monkeypatch.setattr(
        tts,
        "split_text",
        lambda text, max_length=None: ["cached"],
    )
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: "/tmp/cached.ogg")
    monkeypatch.setattr(tts, "_generate_chunk_voice", fail_generate_chunk_voice)

    result = await tts.generate_voice(
        text="cached",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
    )

    assert result == ["/tmp/cached.ogg"]


@pytest.mark.asyncio
async def test_generate_voice_saves_generated_audio_to_cache(monkeypatch) -> None:
    saved = {}

    async def fake_generate_chunk_voice(
        chunk,
        voice,
        rate,
        chunk_index,
        chunks_count,
    ):
        return "/tmp/generated.ogg"

    def fake_save_audio_to_cache(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(
        tts,
        "split_text",
        lambda text, max_length=None: ["generated"],
    )
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "_generate_chunk_voice", fake_generate_chunk_voice)
    monkeypatch.setattr(tts, "save_audio_to_cache", fake_save_audio_to_cache)

    result = await tts.generate_voice(
        text="generated",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
    )

    assert result == ["/tmp/generated.ogg"]
    assert saved == {
        "text": "generated",
        "voice": "uk-UA-PolinaNeural",
        "rate": "+0%",
        "audio_path": "/tmp/generated.ogg",
    }


@pytest.mark.asyncio
async def test_generate_voice_uses_gemini_provider_cache_key(monkeypatch) -> None:
    saved = {}
    captured = {}

    async def fake_generate_gemini_tts_ogg(**kwargs):
        captured.update(kwargs)
        return "/tmp/gemini.ogg"

    async def fail_generate_chunk_voice(*args, **kwargs):
        raise AssertionError("_generate_chunk_voice should not be called")

    def fake_save_audio_to_cache(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(tts, "TTS_PROVIDER", "gemini")
    monkeypatch.setattr(
        tts,
        "split_text",
        lambda text, max_length=None: ["generated"],
    )
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "generate_gemini_tts_ogg", fake_generate_gemini_tts_ogg)
    monkeypatch.setattr(tts, "_generate_chunk_voice", fail_generate_chunk_voice)
    monkeypatch.setattr(tts, "save_audio_to_cache", fake_save_audio_to_cache)

    result = await tts.generate_voice(
        text="generated",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
    )

    assert result == ["/tmp/gemini.ogg"]
    assert saved["text"] == "generated"
    assert saved["voice"].startswith("gemini:")
    assert saved["rate"] == "+0%"
    assert saved["audio_path"] == "/tmp/gemini.ogg"
    assert captured["voice"] == "uk-UA-PolinaNeural"


@pytest.mark.asyncio
async def test_generate_voice_falls_back_to_edge_when_gemini_fails(monkeypatch) -> None:
    saved = {}

    async def fail_generate_gemini_tts_ogg(**kwargs):
        raise RuntimeError("Gemini is unavailable")

    async def fake_generate_chunk_voice(
        chunk,
        voice,
        rate,
        chunk_index,
        chunks_count,
    ):
        return "/tmp/edge.ogg"

    def fake_save_audio_to_cache(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(tts, "TTS_PROVIDER", "gemini")
    monkeypatch.setattr(
        tts,
        "split_text",
        lambda text, max_length=None: ["generated"],
    )
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "generate_gemini_tts_ogg", fail_generate_gemini_tts_ogg)
    monkeypatch.setattr(tts, "_generate_chunk_voice", fake_generate_chunk_voice)
    monkeypatch.setattr(tts, "save_audio_to_cache", fake_save_audio_to_cache)

    result = await tts.generate_voice(
        text="generated",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
    )

    assert result == ["/tmp/edge.ogg"]
    assert saved == {
        "text": "generated",
        "voice": "uk-UA-PolinaNeural",
        "rate": "+0%",
        "audio_path": "/tmp/edge.ogg",
    }


@pytest.mark.asyncio
async def test_generate_voice_uses_edge_cache_after_gemini_failure(monkeypatch) -> None:
    saved = {}
    cache_calls = []

    async def fail_generate_gemini_tts_ogg(**kwargs):
        raise RuntimeError("Gemini is unavailable")

    async def fail_generate_chunk_voice(*args, **kwargs):
        raise AssertionError("_generate_chunk_voice should not be called")

    def fake_get_audio_from_cache(**kwargs):
        cache_calls.append(kwargs)

        if kwargs["voice"].startswith("gemini:"):
            return None

        return "/tmp/cached-edge.ogg"

    def fake_save_audio_to_cache(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(tts, "TTS_PROVIDER", "gemini")
    monkeypatch.setattr(
        tts,
        "split_text",
        lambda text, max_length=None: ["generated"],
    )
    monkeypatch.setattr(tts, "get_audio_from_cache", fake_get_audio_from_cache)
    monkeypatch.setattr(tts, "generate_gemini_tts_ogg", fail_generate_gemini_tts_ogg)
    monkeypatch.setattr(tts, "_generate_chunk_voice", fail_generate_chunk_voice)
    monkeypatch.setattr(tts, "save_audio_to_cache", fake_save_audio_to_cache)

    result = await tts.generate_voice(
        text="generated",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
    )

    assert result == ["/tmp/cached-edge.ogg"]
    assert cache_calls[0]["voice"].startswith("gemini:")
    assert cache_calls[1]["voice"] == "uk-UA-PolinaNeural"
    assert saved == {}


@pytest.mark.asyncio
async def test_generate_voice_uses_configured_provider_chain(monkeypatch) -> None:
    saved = {}

    async def fail_generate_gemini_tts_ogg(**kwargs):
        raise RuntimeError("Gemini is unavailable")

    async def fake_generate_chunk_voice(
        chunk,
        voice,
        rate,
        chunk_index,
        chunks_count,
    ):
        return "/tmp/edge.ogg"

    def fake_save_audio_to_cache(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(tts, "TTS_PROVIDER_CHAIN", ["gemini", "edge"])
    monkeypatch.setattr(
        tts,
        "split_text",
        lambda text, max_length=None: ["generated"],
    )
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "generate_gemini_tts_ogg", fail_generate_gemini_tts_ogg)
    monkeypatch.setattr(tts, "_generate_chunk_voice", fake_generate_chunk_voice)
    monkeypatch.setattr(tts, "save_audio_to_cache", fake_save_audio_to_cache)

    result = await tts.generate_voice(
        text="generated",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
    )

    assert result == ["/tmp/edge.ogg"]
    assert saved["text"] == "generated"
    assert saved["voice"] == "uk-UA-PolinaNeural"
    assert saved["rate"] == "+0%"
    assert saved["audio_path"] == "/tmp/edge.ogg"


@pytest.mark.asyncio
async def test_generate_voice_falls_back_to_edge_after_gemini_quota_without_error_log(
    monkeypatch,
    caplog,
) -> None:
    saved = {}

    async def fail_gemini_quota(**kwargs):
        raise tts.GeminiQuotaExceededError("Gemini quota exhausted")

    async def fake_generate_chunk_voice(
        chunk,
        voice,
        rate,
        chunk_index,
        chunks_count,
    ):
        return "/tmp/edge.ogg"

    def fake_save_audio_to_cache(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(tts, "TTS_PROVIDER_CHAIN", ["gemini", "edge"])
    monkeypatch.setattr(
        tts,
        "split_text",
        lambda text, max_length=None: ["generated"],
    )
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "generate_gemini_tts_ogg", fail_gemini_quota)
    monkeypatch.setattr(tts, "_generate_chunk_voice", fake_generate_chunk_voice)
    monkeypatch.setattr(tts, "save_audio_to_cache", fake_save_audio_to_cache)

    result = await tts.generate_voice(
        text="generated",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
    )

    assert result == ["/tmp/edge.ogg"]
    assert saved["voice"] == "uk-UA-PolinaNeural"
    assert "fallback continues" in caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.asyncio
async def test_generate_voice_ignores_removed_provider_in_explicit_chain(
    monkeypatch,
) -> None:
    saved = {}

    async def fake_generate_chunk_voice(
        chunk,
        voice,
        rate,
        chunk_index,
        chunks_count,
    ):
        return "/tmp/edge.ogg"

    def fake_save_audio_to_cache(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(
        tts,
        "split_text",
        lambda text, max_length=None: ["generated"],
    )
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "_generate_chunk_voice", fake_generate_chunk_voice)
    monkeypatch.setattr(tts, "save_audio_to_cache", fake_save_audio_to_cache)

    result = await tts.generate_voice(
        text="generated",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        provider_chain=["removed-provider", "edge"],
        raise_on_error=True,
    )

    assert result == ["/tmp/edge.ogg"]
    assert saved["voice"] == "uk-UA-PolinaNeural"


@pytest.mark.asyncio
async def test_generate_voice_uses_gemini_chunk_limit(monkeypatch) -> None:
    captured = {}

    async def fake_generate_gemini_tts_ogg(**kwargs):
        return "/tmp/gemini.ogg"

    def fake_split_text(text, max_length=None):
        captured["max_length"] = max_length
        return ["generated"]

    monkeypatch.setattr(tts, "TTS_PROVIDER_CHAIN", ["gemini", "edge"])
    monkeypatch.setattr(tts, "split_text", fake_split_text)
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "generate_gemini_tts_ogg", fake_generate_gemini_tts_ogg)
    monkeypatch.setattr(tts, "save_audio_to_cache", lambda **kwargs: None)

    result = await tts.generate_voice(
        text="generated",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
    )

    assert result == ["/tmp/gemini.ogg"]
    assert captured["max_length"] == tts.GEMINI_TTS_CHUNK_MAX_LENGTH


@pytest.mark.asyncio
async def test_generate_voice_reports_progress(monkeypatch) -> None:
    events = []

    async def fake_generate_chunk_voice(
        chunk,
        voice,
        rate,
        chunk_index,
        chunks_count,
    ):
        return f"/tmp/{chunk_index}.ogg"

    async def progress_callback(completed, total, provider, cache_hit):
        events.append((completed, total, provider, cache_hit))

    monkeypatch.setattr(
        tts,
        "split_text",
        lambda text, max_length=None: ["one", "two"],
    )
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "_generate_chunk_voice", fake_generate_chunk_voice)
    monkeypatch.setattr(tts, "save_audio_to_cache", lambda **kwargs: None)

    result = await tts.generate_voice(
        text="one two",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
        progress_callback=progress_callback,
    )

    assert result == ["/tmp/1.ogg", "/tmp/2.ogg"]
    assert events == [
        (1, 2, "edge", False),
        (2, 2, "edge", False),
    ]


@pytest.mark.asyncio
async def test_generate_voice_returns_empty_list_for_empty_chunks(monkeypatch) -> None:
    monkeypatch.setattr(tts, "split_text", lambda text, max_length=None: [])

    result = await tts.generate_voice(
        text="text",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
    )

    assert result == []
