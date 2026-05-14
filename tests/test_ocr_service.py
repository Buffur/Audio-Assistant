import pytest
from PIL import Image

from services import ocr


def test_normalize_ocr_text_trims_lines_and_spaces() -> None:
    assert ocr._normalize_ocr_text("  Перший   рядок \r\n\n Другий\tрядок ") == (
        "Перший рядок\nДругий рядок"
    )


@pytest.mark.asyncio
async def test_extract_text_with_providers_uses_gemini(monkeypatch) -> None:
    image = Image.new("RGB", (10, 10), "white")

    async def fake_gemini(received_image):
        assert received_image is image
        return "Gemini розпізнав текст"

    monkeypatch.setattr(ocr, "_extract_with_gemini", fake_gemini)

    try:
        result = await ocr._extract_text_with_providers("photo.png", image)
    finally:
        image.close()

    assert result == "Gemini розпізнав текст"


@pytest.mark.asyncio
async def test_extract_text_with_providers_returns_no_text_for_empty_gemini(
    monkeypatch,
) -> None:
    image = Image.new("RGB", (10, 10), "white")

    async def empty_gemini(received_image):
        assert received_image is image
        return ""

    monkeypatch.setattr(ocr, "_extract_with_gemini", empty_gemini)

    try:
        result = await ocr._extract_text_with_providers("photo.png", image)
    finally:
        image.close()

    assert result == ocr.OCR_NO_TEXT_MESSAGE


@pytest.mark.asyncio
async def test_extract_text_with_providers_returns_no_text_when_gemini_fails(
    monkeypatch,
) -> None:
    image = Image.new("RGB", (10, 10), "white")

    async def fail_gemini(received_image):
        assert received_image is image
        raise RuntimeError("Gemini unavailable")

    monkeypatch.setattr(ocr, "_extract_with_gemini", fail_gemini)

    try:
        result = await ocr._extract_text_with_providers("photo.png", image)
    finally:
        image.close()

    assert result == ocr.OCR_NO_TEXT_MESSAGE
