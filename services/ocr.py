# Файл: services/ocr.py

import logging
import os
import re

import PIL.Image
from google.genai import types

from config import (
    GEMINI_OCR_MODEL,
    GEMINI_OCR_MODEL_CHAIN,
    OCR_IMAGE_OPEN_TIMEOUT_SECONDS,
    OCR_MIN_TEXT_LENGTH,
    OCR_TOTAL_TIMEOUT_SECONDS,
)
from services.gemini_client import generate_gemini_content_with_fallback
from services.operation_timeouts import (
    OperationTimeoutError,
    run_sync_with_timeout,
    run_with_timeout,
)

logger = logging.getLogger(__name__)

OCR_MODEL = GEMINI_OCR_MODEL
OCR_MODEL_CHAIN = GEMINI_OCR_MODEL_CHAIN
OCR_NO_TEXT_MESSAGE = (
    "❌ Не бачу тексту на фото. "
    "Спробуйте надіслати чіткіше фото: ближче до тексту, без сильного нахилу "
    "та з нормальним освітленням."
)
OCR_GENERIC_ERROR_MESSAGE = (
    "❌ Не вдалося розпізнати текст із фотографії. "
    "Спробуйте ще раз або надішліть чіткіше зображення."
)
OCR_TIMEOUT_MESSAGE = (
    "❌ Розпізнавання тексту зайняло занадто багато часу. "
    "Спробуйте менше або чіткіше зображення."
)

# Захист від надто великих зображень.
MAX_IMAGE_PIXELS = 20_000_000
PIL.Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

OCR_PROMPT = """
Ти — інструмент доступності для незрячих. Користувач сфотографував текст
(документ, накладну, етикетку, інструкцію тощо).

Будь ласка, розпізнай і витягни ВЕСЬ текст із цього зображення.
Автоматично визнач мову тексту. Не перекладай: збережи оригінальну мову,
алфавіт, числа, імена, дати, структуру рядків і важливі позначення.

Поверни ТІЛЬКИ розпізнаний текст, без жодних твоїх коментарів чи вступних слів.

Якщо на фото взагалі немає тексту, поверни точну фразу:
"❌ Не бачу тексту на фото."
""".strip()

def _open_image(image_path: str) -> PIL.Image.Image:
    """
    Відкриває зображення через PIL і примусово завантажує його в пам'ять.

    image.load() потрібен, щоб помилки пошкодженого файлу з'явилися одразу,
    а не пізніше під час передачі в Gemini.
    """
    image = PIL.Image.open(image_path)
    image.load()
    return image


def _normalize_ocr_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []

    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()

        if line:
            lines.append(line)

    return "\n".join(lines).strip()


def _is_usable_ocr_text(text: str) -> bool:
    if not text or text.startswith("❌"):
        return False

    return len(text) >= OCR_MIN_TEXT_LENGTH


async def _extract_with_gemini(image: PIL.Image.Image) -> str:
    response = await generate_gemini_content_with_fallback(
        primary_model=OCR_MODEL,
        fallback_models=OCR_MODEL_CHAIN,
        contents=[OCR_PROMPT, image],
        config=types.GenerateContentConfig(
            temperature=0.1,
        ),
        context="ocr",
    )

    return _normalize_ocr_text(response.text or "")


async def _extract_text_with_providers(
    image_path: str,
    image: PIL.Image.Image,
) -> str:
    try:
        text = await _extract_with_gemini(image)

        if _is_usable_ocr_text(text):
            logger.info(
                "OCR: provider=gemini успішно розпізнав text_length=%s",
                len(text),
            )
            return text

        logger.warning(
            "OCR: provider=gemini повернув порожню або надто коротку відповідь для %s",
            image_path,
        )

    except Exception as error:
        logger.warning("OCR: provider=gemini недоступний для %s: %s", image_path, error)

    return OCR_NO_TEXT_MESSAGE


async def extract_text_from_image(image_path: str) -> str:
    """
    Розпізнає текст із фотографії через Gemini OCR.
    """
    if not os.path.exists(image_path):
        logger.error("OCR: файл зображення не знайдено: %s", image_path)
        return "❌ Файл зображення не знайдено."

    image = None

    try:
        # Виконуємо синхронний I/O-код PIL в окремому потоці,
        # щоб не блокувати event loop.
        image = await run_sync_with_timeout(
            _open_image,
            image_path,
            operation="ocr_image_open",
            timeout_seconds=OCR_IMAGE_OPEN_TIMEOUT_SECONDS,
        )

        return await run_with_timeout(
            _extract_text_with_providers(image_path, image),
            operation="ocr_total",
            timeout_seconds=OCR_TOTAL_TIMEOUT_SECONDS,
        )

    except OperationTimeoutError as error:
        logger.warning(
            "OCR: timeout for image=%s operation=%s timeout=%s",
            image_path,
            error.operation,
            error.timeout_seconds,
        )
        return OCR_TIMEOUT_MESSAGE

    except PIL.Image.DecompressionBombError:
        logger.exception(
            "OCR: зображення занадто велике або потенційно небезпечне: %s",
            image_path,
        )
        return (
            "❌ Зображення занадто велике для обробки. "
            "Спробуйте надіслати менше або обрізане фото."
        )

    except PIL.UnidentifiedImageError:
        logger.exception("OCR: файл не є коректним зображенням: %s", image_path)
        return (
            "❌ Не вдалося відкрити зображення. "
            "Перевірте файл і спробуйте ще раз."
        )

    except Exception:
        logger.exception(
            "OCR: помилка розпізнавання тексту з фотографії: %s",
            image_path,
        )
        return OCR_GENERIC_ERROR_MESSAGE

    finally:
        if image is not None:
            image.close()
