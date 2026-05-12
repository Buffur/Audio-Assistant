# Файл: services/ocr.py

import asyncio
import logging
import os

import PIL.Image
from google import genai
from google.genai import types

from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

OCR_MODEL = "gemini-3.1-flash-lite-preview"

# Захист від надто великих зображень.
# 20 млн пікселів — достатньо для більшості фото документів,
# але допомагає не перевантажити пам'ять.
MAX_IMAGE_PIXELS = 20_000_000
PIL.Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

OCR_PROMPT = """
Ти — інструмент доступності для незрячих. Користувач сфотографував текст
(документ, накладну, етикетку, інструкцію тощо).

Будь ласка, розпізнай і витягни ВЕСЬ текст із цього зображення.

Поверни ТІЛЬКИ розпізнаний текст, без жодних твоїх коментарів чи вступних слів.

Якщо на фото взагалі немає тексту, поверни точну фразу:
"❌ На цьому фото не знайдено тексту."
""".strip()

# Використовуємо клієнт Gemini для OCR.
ai_client = genai.Client(api_key=GEMINI_API_KEY)


def _open_image(image_path: str) -> PIL.Image.Image:
    """
    Відкриває зображення через PIL і примусово завантажує його в пам'ять.

    image.load() потрібен, щоб помилки пошкодженого файлу з'явилися одразу,
    а не пізніше під час передачі в Gemini.
    """
    image = PIL.Image.open(image_path)
    image.load()
    return image


async def extract_text_from_image(image_path: str) -> str:
    """
    Відправляє фотографію до ШІ для витягування тексту.
    """
    if not os.path.exists(image_path):
        logger.error("OCR: файл зображення не знайдено: %s", image_path)
        return "❌ Файл зображення не знайдено."

    image = None

    try:
        # Виконуємо синхронний I/O-код PIL в окремому потоці,
        # щоб не блокувати event loop.
        image = await asyncio.to_thread(_open_image, image_path)

        response = await ai_client.aio.models.generate_content(
            model=OCR_MODEL,
            contents=[OCR_PROMPT, image],
            config=types.GenerateContentConfig(
                temperature=0.1,
            )
        )

        if not response.text:
            logger.warning("OCR: Gemini повернув порожню відповідь для файлу: %s", image_path)
            return "❌ Не вдалося розпізнати текст на фотографії."

        return response.text.strip()

    except PIL.Image.DecompressionBombError:
        logger.exception("OCR: зображення занадто велике або потенційно небезпечне: %s", image_path)
        return "❌ Зображення занадто велике для обробки."

    except PIL.UnidentifiedImageError:
        logger.exception("OCR: файл не є коректним зображенням: %s", image_path)
        return "❌ Не вдалося відкрити зображення. Перевірте файл і спробуйте ще раз."

    except Exception:
        logger.exception("OCR: помилка розпізнавання тексту з фотографії: %s", image_path)
        return "❌ Помилка розпізнавання тексту з фотографії. Спробуйте ще раз."

    finally:
        if image is not None:
            image.close()