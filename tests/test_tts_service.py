import pytest

from services import tts


@pytest.fixture(autouse=True)
def use_default_edge_provider(monkeypatch) -> None:
    monkeypatch.setattr(tts, "TTS_PROVIDER", "edge")
    monkeypatch.setattr(tts, "TTS_PROVIDER_CHAIN", [])


def test_validate_tts_input_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        tts._validate_tts_input("", "voice", "+0%")

    with pytest.raises(ValueError):
        tts._validate_tts_input("text", "", "+0%")

    with pytest.raises(ValueError):
        tts._validate_tts_input("text", "voice", None)


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

    monkeypatch.setattr(tts, "split_text", lambda text: ["one", "two"])
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

    monkeypatch.setattr(tts, "split_text", lambda text: ["cached"])
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

    monkeypatch.setattr(tts, "split_text", lambda text: ["generated"])
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
    monkeypatch.setattr(tts, "split_text", lambda text: ["generated"])
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
    monkeypatch.setattr(tts, "split_text", lambda text: ["generated"])
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
    monkeypatch.setattr(tts, "split_text", lambda text: ["generated"])
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

    async def fake_generate_piper_tts_ogg(**kwargs):
        return "/tmp/piper.ogg"

    async def fail_generate_chunk_voice(*args, **kwargs):
        raise AssertionError("_generate_chunk_voice should not be called")

    def fake_save_audio_to_cache(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(tts, "TTS_PROVIDER_CHAIN", ["gemini", "piper", "edge"])
    monkeypatch.setattr(tts, "split_text", lambda text: ["generated"])
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "generate_gemini_tts_ogg", fail_generate_gemini_tts_ogg)
    monkeypatch.setattr(tts, "generate_piper_tts_ogg", fake_generate_piper_tts_ogg)
    monkeypatch.setattr(tts, "_generate_chunk_voice", fail_generate_chunk_voice)
    monkeypatch.setattr(tts, "save_audio_to_cache", fake_save_audio_to_cache)

    result = await tts.generate_voice(
        text="generated",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        raise_on_error=True,
    )

    assert result == ["/tmp/piper.ogg"]
    assert saved["text"] == "generated"
    assert saved["voice"].startswith("piper:")
    assert saved["rate"] == "+0%"
    assert saved["audio_path"] == "/tmp/piper.ogg"


@pytest.mark.asyncio
async def test_generate_voice_uses_edge_after_gemini_and_piper_fail(
    monkeypatch,
) -> None:
    saved = {}

    async def fail_generate_gemini_tts_ogg(**kwargs):
        raise RuntimeError("Gemini is unavailable")

    async def fail_generate_piper_tts_ogg(**kwargs):
        raise RuntimeError("Piper is unavailable")

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

    monkeypatch.setattr(tts, "TTS_PROVIDER_CHAIN", ["gemini", "piper", "edge"])
    monkeypatch.setattr(tts, "split_text", lambda text: ["generated"])
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "generate_gemini_tts_ogg", fail_generate_gemini_tts_ogg)
    monkeypatch.setattr(tts, "generate_piper_tts_ogg", fail_generate_piper_tts_ogg)
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
async def test_generate_voice_uses_explicit_provider_chain(monkeypatch) -> None:
    saved = {}

    async def fake_generate_piper_tts_ogg(**kwargs):
        return "/tmp/piper.ogg"

    async def fail_generate_chunk_voice(*args, **kwargs):
        raise AssertionError("_generate_chunk_voice should not be called")

    def fake_save_audio_to_cache(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(tts, "split_text", lambda text: ["generated"])
    monkeypatch.setattr(tts, "get_audio_from_cache", lambda **kwargs: None)
    monkeypatch.setattr(tts, "generate_piper_tts_ogg", fake_generate_piper_tts_ogg)
    monkeypatch.setattr(tts, "_generate_chunk_voice", fail_generate_chunk_voice)
    monkeypatch.setattr(tts, "save_audio_to_cache", fake_save_audio_to_cache)

    result = await tts.generate_voice(
        text="generated",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
        provider_chain=["piper", "edge"],
        raise_on_error=True,
    )

    assert result == ["/tmp/piper.ogg"]
    assert saved["voice"].startswith("piper:")


@pytest.mark.asyncio
async def test_generate_voice_returns_empty_list_for_empty_chunks(monkeypatch) -> None:
    monkeypatch.setattr(tts, "split_text", lambda text: [])

    result = await tts.generate_voice(
        text="text",
        voice="uk-UA-PolinaNeural",
        rate="+0%",
    )

    assert result == []
