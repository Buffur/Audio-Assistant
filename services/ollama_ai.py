# Файл: services/ollama_ai.py

import logging
import re

import aiohttp

from config import (
    OLLAMA_BASE_URL,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


def _strip_ollama_output(text: str) -> str:
    if not text:
        return ""

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"^\s*```(?:text|markdown)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```\s*$", "", text)

    return text.strip()


async def generate_ollama_text(
    *,
    prompt: str,
    temperature: float,
) -> str:
    """
    Генерує текст через локальний Ollama HTTP API.
    """
    base_url = OLLAMA_BASE_URL.rstrip("/")
    timeout = aiohttp.ClientTimeout(total=OLLAMA_TIMEOUT_SECONDS)
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": temperature,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{base_url}/api/chat", json=payload) as response:
            response.raise_for_status()
            data = await response.json()

    content = (data.get("message") or {}).get("content") or ""
    result = _strip_ollama_output(content)

    if not result:
        raise RuntimeError("Ollama returned an empty response.")

    logger.info(
        "OllamaAI: model=%s generated text_length=%s",
        OLLAMA_MODEL,
        len(result),
    )

    return result
