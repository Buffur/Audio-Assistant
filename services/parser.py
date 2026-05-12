# Файл: services/parser.py

import asyncio
import ipaddress
import logging
import re
import socket
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

# ============================================================
# НАЛАШТУВАННЯ
# ============================================================

REQUEST_TIMEOUT = 20
MAX_HTML_BYTES = 2_000_000
MAX_RAW_TEXT_FOR_AI = 30_000
MIN_ARTICLE_LENGTH = 50
MAX_REDIRECTS = 5

AI_MODEL = "gemini-3.1-flash-lite-preview"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "text/plain;q=0.8,*/*;q=0.7"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8,ru;q=0.7",
}

REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


# ============================================================
# GEMINI CLIENT
# ============================================================

try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    logger.error("Не вдалося ініціалізувати Gemini client: %s", e)
    ai_client = None


# ============================================================
# ГЛОБАЛЬНА HTTP-СЕСІЯ
# ============================================================

_http_session: Optional[aiohttp.ClientSession] = None


async def get_http_session() -> aiohttp.ClientSession:
    """
    Повертає глобальну aiohttp-сесію.

    Якщо її ще немає або вона закрита — створює нову.
    """
    global _http_session

    if _http_session is None or _http_session.closed:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        _http_session = aiohttp.ClientSession(
            headers=HEADERS,
            timeout=timeout,
        )
        logger.info("Створено нову глобальну aiohttp-сесію.")

    return _http_session


async def close_http_session() -> None:
    """
    Закриває глобальну aiohttp-сесію.

    Цю функцію бажано викликати у bot.py в блоці finally,
    коли бот завершує роботу.
    """
    global _http_session

    if _http_session is not None and not _http_session.closed:
        await _http_session.close()
        logger.info("Глобальну aiohttp-сесію закрито.")


# ============================================================
# URL HELPERS
# ============================================================

def extract_first_url(text: str) -> str | None:
    """
    Витягує перше http/https-посилання з довільного тексту.

    Приклади:
    - "https://example.com/news" -> "https://example.com/news"
    - "прочитай це https://example.com/news" -> "https://example.com/news"
    """
    if not text:
        return None

    match = re.search(r"https?://[^\s<>()\"']+", text)

    if not match:
        return None

    url = match.group(0).strip()

    # Прибираємо типові знаки пунктуації у кінці речення.
    return url.rstrip(".,!?;:)")


def _is_valid_url(url: str) -> bool:
    """
    Перевіряє, що посилання має коректний http/https формат.
    """
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        if not parsed.netloc or not parsed.hostname:
            return False

        # Забороняємо URL з логіном/паролем:
        # https://user:pass@example.com
        if parsed.username or parsed.password:
            return False

        return True

    except Exception:
        return False


def _is_private_ip(ip: str) -> bool:
    """
    Перевіряє, чи IP є приватним/локальним/службовим.
    Це базовий захист від SSRF.
    """
    try:
        ip_obj = ipaddress.ip_address(ip)

        return any(
            [
                ip_obj.is_private,
                ip_obj.is_loopback,
                ip_obj.is_link_local,
                ip_obj.is_multicast,
                ip_obj.is_reserved,
                ip_obj.is_unspecified,
            ]
        )

    except ValueError:
        return False


async def _is_safe_url_for_request(url: str) -> bool:
    """
    Додаткова перевірка URL перед завантаженням.

    Захищає від очевидних локальних адрес:
    - localhost
    - 127.0.0.1
    - 10.x.x.x
    - 192.168.x.x
    - 172.16.x.x - 172.31.x.x
    - ::1
    """
    parsed = urlparse(url)
    hostname = parsed.hostname

    if not hostname:
        return False

    hostname_lower = hostname.lower()

    blocked_hosts = {
        "localhost",
        "localhost.localdomain",
    }

    if hostname_lower in blocked_hosts:
        return False

    if hostname_lower.endswith(".local"):
        return False

    # Якщо hostname уже є IP-адресою.
    if _is_private_ip(hostname_lower):
        return False

    # Якщо hostname є доменом — пробуємо резолвити IP.
    try:
        addr_info = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            None,
        )

        for item in addr_info:
            ip = item[4][0]

            if _is_private_ip(ip):
                return False

    except Exception as e:
        logger.warning("Не вдалося перевірити hostname %s: %s", hostname, e)
        return False

    return True


async def _is_valid_and_safe_url(url: str) -> bool:
    """
    Перевіряє URL повністю:
    - формат;
    - схема;
    - відсутність login/password;
    - відсутність приватних/локальних IP.
    """
    if not _is_valid_url(url):
        return False

    return await _is_safe_url_for_request(url)


def _build_redirect_url(base_url: str, location: str) -> str:
    """
    Створює абсолютний URL для redirect Location.

    Location може бути:
    - абсолютним: https://example.com/new
    - відносним: /new
    """
    return urljoin(base_url, location.strip())


# ============================================================
# TEXT CLEANING
# ============================================================

def _normalize_whitespace(text: str) -> str:
    """
    Прибирає зайві пробіли, таби та надлишкові переноси.
    """
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def clean_text_for_tts(text: str) -> str:
    """
    Фінальна зачистка тексту перед TTS.

    - Замінює довгі посилання на короткий домен.
    - Прибирає зайві пробіли.
    - Нормалізує переноси рядків.
    """
    if not text:
        return ""

    def replace_url(match: re.Match) -> str:
        try:
            domain = urlparse(match.group(0)).netloc.replace("www.", "")
            return f" {domain} "
        except Exception:
            return " "

    text = re.sub(r"https?://[^\s<>()\"']+", replace_url, text)
    text = _normalize_whitespace(text)

    return text


def _strip_ai_output(text: str) -> str:
    """
    Очищає відповідь AI від markdown-обгорток і зайвих службових фраз.
    """
    if not text:
        return ""

    text = text.strip()
    text = re.sub(
        r"^```(?:text|html|markdown)?",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(r"```$", "", text).strip()

    bad_prefixes = [
        "Ось очищений текст статті:",
        "Ось текст статті:",
        "Текст статті:",
        "Очищений текст:",
    ]

    for prefix in bad_prefixes:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()

    return _normalize_whitespace(text)


# ============================================================
# AI EXTRACTION
# ============================================================

async def _extract_with_ai(raw_text: str) -> Optional[str]:
    """
    Спроба витягти основний текст статті за допомогою Gemini.

    Якщо AI недоступний або повертає поганий результат —
    повертає None, після чого parse_article використовує fallback-парсер.
    """
    if not ai_client:
        logger.warning("Gemini client недоступний.")
        return None

    if not raw_text or len(raw_text.strip()) < 100:
        return None

    raw_text = raw_text[:MAX_RAW_TEXT_FOR_AI]

    prompt = f"""
Ти — інклюзивний інструмент доступності для незрячих користувачів.
Твоє завдання — витягнути з тексту сторінки тільки основний зміст статті або новини.

Правила:
1. Поверни тільки чистий текст статті.
2. Залиш заголовок, автора, дату, основні абзаци, якщо вони є.
3. Видали меню, рекламу, cookie-повідомлення, навігацію, коментарі,
   блоки "Читайте також", кнопки поширення, підписки та службовий текст.
4. Не додавай власних пояснень.
5. Не використовуй Markdown.
6. Якщо текст не схожий на статтю або новину, все одно спробуй повернути
   головний корисний текст сторінки.

ТЕКСТ СТОРІНКИ:
{raw_text}
"""

    try:
        response = await ai_client.aio.models.generate_content(
            model=AI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
            ),
        )

        result = _strip_ai_output(response.text or "")

        if len(result) < MIN_ARTICLE_LENGTH:
            return None

        return result

    except Exception as e:
        logger.error("Помилка AI-парсингу: %s", e)
        return None


# ============================================================
# FALLBACK PARSER
# ============================================================

ARTICLE_SELECTORS = [
    ("article", {}),
    ("main", {}),
    (
        "div",
        {
            "class": re.compile(
                r"(article|post|entry|content|news|story|text|body)",
                re.I,
            )
        },
    ),
    (
        "section",
        {
            "class": re.compile(
                r"(article|post|entry|content|news|story|text|body)",
                re.I,
            )
        },
    ),
    (
        "div",
        {
            "id": re.compile(
                r"(article|post|entry|content|news|story|text|body)",
                re.I,
            )
        },
    ),
]

JUNK_SELECTORS = [
    "comments",
    "comment",
    "tags",
    "share",
    "social",
    "banner",
    "promo",
    "read-more",
    "related",
    "telegram",
    "subscribe",
    "advert",
    "ad-",
    "ads",
    "sponsor",
    "cookie",
    "popup",
    "modal",
    "menu",
    "navbar",
    "breadcrumb",
    "tooltip",
    "list-info",
    "btn-link",
    "footer",
    "header",
    "sidebar",
]

STOP_PHRASES = [
    "подякуй журналісту",
    "слідкуйте за новинами",
    "стежте за новинами",
    "коментарі",
    "читайте також",
    "підписуйтесь",
    "підписатися",
    "поширити",
    "share",
    "subscribe",
    "advertisement",
    "реклама",
    "cookie",
]


def _get_meta_content(soup: BeautifulSoup, *selectors: tuple[str, dict]) -> str:
    """
    Шукає content у meta-тегах.
    """
    for tag_name, attrs in selectors:
        tag = soup.find(tag_name, attrs=attrs)

        if tag and tag.get("content"):
            return tag["content"].strip()

    return ""


def _extract_title(soup: BeautifulSoup) -> str:
    """
    Витягує заголовок.
    """
    h1 = soup.find("h1")

    if h1:
        title = h1.get_text(" ", strip=True)
        h1.decompose()

        if title:
            return title

    meta_title = _get_meta_content(
        soup,
        ("meta", {"property": "og:title"}),
        ("meta", {"name": "twitter:title"}),
    )

    if meta_title:
        return meta_title

    if soup.title:
        return soup.title.get_text(" ", strip=True)

    return ""


def _extract_author(soup: BeautifulSoup) -> str:
    """
    Витягує автора, якщо він є.
    """
    meta_author = _get_meta_content(
        soup,
        ("meta", {"name": "author"}),
        ("meta", {"property": "article:author"}),
    )

    if meta_author and len(meta_author) < 100:
        return meta_author

    author_el = (
        soup.find(attrs={"itemprop": "author"})
        or soup.find(class_=re.compile(r"author", re.I))
        or soup.find(id=re.compile(r"author", re.I))
    )

    if author_el:
        author = author_el.get_text(" ", strip=True)

        if author and len(author) < 100:
            return author

    return ""


def _extract_date(soup: BeautifulSoup) -> str:
    """
    Витягує дату публікації, якщо вона є.
    """
    meta_date = _get_meta_content(
        soup,
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "date"}),
        ("meta", {"name": "pubdate"}),
        ("meta", {"itemprop": "datePublished"}),
    )

    if meta_date:
        return meta_date

    time_tag = soup.find("time")

    if time_tag:
        datetime_value = time_tag.get("datetime")

        if datetime_value:
            return datetime_value.strip()

        text_value = time_tag.get_text(" ", strip=True)

        if text_value:
            return text_value

    return ""


def _remove_junk_tags(soup: BeautifulSoup) -> None:
    """
    Видаляє очевидне сміття зі сторінки.
    """
    for element in soup(
        [
            "script",
            "style",
            "noscript",
            "nav",
            "footer",
            "header",
            "aside",
            "form",
            "svg",
            "button",
            "iframe",
            "canvas",
        ]
    ):
        element.decompose()

    for tag in soup.find_all():
        attrs = getattr(tag, "attrs", {}) or {}
        classes = attrs.get("class", [])
        tag_id = attrs.get("id", "")

        if isinstance(classes, str):
            classes = [classes]

        combined = " ".join(classes + [str(tag_id)]).lower()

        if not combined:
            continue

        # Не видаляємо потенційно корисні контейнери статті.
        if any(
            keep in combined
            for keep in [
                "article",
                "post-content",
                "entry-content",
                "article-text",
                "news-text",
            ]
        ):
            continue

        if any(junk in combined for junk in JUNK_SELECTORS):
            tag.decompose()

    for node in list(soup.find_all(string=True)):
        text = node.get_text(" ", strip=True).lower()

        if not text:
            continue

        if any(phrase in text for phrase in STOP_PHRASES):
            parent = node.parent

            if (
                parent
                and parent.name in ["p", "div", "li", "span"]
                and len(parent.get_text(" ", strip=True)) < 350
            ):
                parent.decompose()


def _collect_text_from_container(container) -> str:
    """
    Збирає текст із контейнера, зберігаючи логічні паузи між абзацами.
    """
    blocks = container.find_all(["p", "h2", "h3", "h4", "li", "blockquote"])

    if blocks:
        parts = []

        for block in blocks:
            text = block.get_text(" ", strip=True)
            text = _normalize_whitespace(text)

            if len(text) > 15:
                parts.append(text)

        return "\n\n".join(parts)

    return container.get_text("\n\n", strip=True)


def _fallback_parse(soup: BeautifulSoup) -> str:
    """
    Класичний fallback-парсер через BeautifulSoup.
    Використовується, якщо AI не спрацював.
    """
    title = _extract_title(soup)
    author = _extract_author(soup)
    date = _extract_date(soup)

    _remove_junk_tags(soup)

    parts = []

    if title:
        parts.append(title)

    if author:
        parts.append(f"Автор: {author}.")

    if date:
        parts.append(f"Дата: {date}.")

    main_text = ""

    for tag_name, attrs in ARTICLE_SELECTORS:
        container = soup.find(tag_name, attrs=attrs)

        if container:
            candidate = _collect_text_from_container(container)

            if len(candidate) > len(main_text):
                main_text = candidate

    if not main_text or len(main_text) < 150:
        paragraphs = soup.find_all("p")
        valid_paragraphs = []

        for paragraph in paragraphs:
            text = paragraph.get_text(" ", strip=True)
            text = _normalize_whitespace(text)

            if len(text) > 30:
                valid_paragraphs.append(text)

        main_text = "\n\n".join(valid_paragraphs)

    if main_text:
        parts.append(main_text)

    result = "\n\n".join(parts)

    # Фінальна зачистка від типових артефактів.
    cleanup_patterns = [
        r"\b\d+\s*Коментар\w*",
        r"\b\d+\s*Перегляд\w*",
        r"\bvisibility\b",
        r"\bchat_bubble\b",
        r"\bshare\b",
        r"\bprint\b",
        r"\bemail\b",
    ]

    for pattern in cleanup_patterns:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)

    return _normalize_whitespace(result)


# ============================================================
# HTML LOADING
# ============================================================

async def _read_limited_response(resp: aiohttp.ClientResponse) -> str:
    """
    Читає відповідь частинами, щоб не завантажити надто велику сторінку
    в пам'ять.
    """
    chunks = []
    total_size = 0

    async for chunk in resp.content.iter_chunked(8192):
        total_size += len(chunk)

        if total_size > MAX_HTML_BYTES:
            raise ValueError("HTML сторінка занадто велика.")

        chunks.append(chunk)

    raw = b"".join(chunks)
    charset = resp.charset or "utf-8"

    try:
        return raw.decode(charset, errors="ignore")
    except LookupError:
        return raw.decode("utf-8", errors="ignore")


def _is_supported_content_type(content_type: str) -> bool:
    """
    Перевіряє, чи можна читати відповідь як HTML/XML/TXT.
    """
    if not content_type:
        return True

    content_type = content_type.lower()

    allowed_content_types = [
        "text/html",
        "text/plain",
        "application/xhtml+xml",
        "application/xml",
    ]

    return any(item in content_type for item in allowed_content_types)


async def _load_html(url: str) -> str | None:
    """
    Завантажує HTML сторінки.

    Редиректи обробляються вручну, щоб кожний наступний URL
    проходив перевірку безпеки перед запитом.
    """
    session = await get_http_session()
    current_url = url

    for redirect_number in range(MAX_REDIRECTS + 1):
        if not await _is_valid_and_safe_url(current_url):
            logger.warning(
                "Небезпечний або некоректний URL під час redirect-перевірки: %s",
                current_url,
            )
            return None

        async with session.get(
            current_url,
            allow_redirects=False,
        ) as resp:
            if resp.status in REDIRECT_STATUS_CODES:
                location = resp.headers.get("Location")

                if not location:
                    logger.warning(
                        "Redirect без Location для URL %s",
                        current_url,
                    )
                    return None

                if redirect_number >= MAX_REDIRECTS:
                    raise ValueError("Забагато редиректів.")

                next_url = _build_redirect_url(str(resp.url), location)

                logger.info(
                    "Redirect %s -> %s",
                    current_url,
                    next_url,
                )

                current_url = next_url
                continue

            if resp.status >= 400:
                logger.warning(
                    "Сторінка повернула HTTP %s для URL %s",
                    resp.status,
                    current_url,
                )
                return None

            content_type = resp.headers.get("Content-Type", "")

            if not _is_supported_content_type(content_type):
                logger.warning(
                    "Непідтримуваний Content-Type %s для URL %s",
                    content_type,
                    current_url,
                )
                return None

            return await _read_limited_response(resp)

    raise ValueError("Забагато редиректів.")


# ============================================================
# PUBLIC API
# ============================================================

async def parse_article(url: str) -> str:
    """
    Головна функція парсингу статті.

    Може приймати:
    - чистий URL;
    - повідомлення, в якому є URL.
    """
    extracted_url = extract_first_url(url)

    if extracted_url:
        url = extracted_url

    if not _is_valid_url(url):
        return "❌ Некоректне посилання."

    if not await _is_safe_url_for_request(url):
        return "❌ Це посилання не можна обробити з міркувань безпеки."

    try:
        html = await _load_html(url)

        if not html:
            return "❌ Помилка завантаження сторінки."

    except ValueError as e:
        logger.warning("Сторінку не оброблено: %s", e)
        return "❌ Сторінка занадто велика для обробки."

    except asyncio.TimeoutError:
        logger.error("Тайм-аут при завантаженні URL: %s", url)
        return "❌ Сторінка завантажується занадто довго."

    except Exception as e:
        logger.error("Мережева помилка при завантаженні %s: %s", url, e)
        return "❌ Помилка завантаження сторінки."

    soup = BeautifulSoup(html, "html.parser")
    raw_soup = BeautifulSoup(html, "html.parser")

    for element in raw_soup(
        [
            "script",
            "style",
            "noscript",
            "nav",
            "footer",
            "header",
            "aside",
            "form",
            "svg",
            "button",
            "iframe",
        ]
    ):
        element.decompose()

    raw_text = raw_soup.get_text(separator="\n", strip=True)
    raw_text = _normalize_whitespace(raw_text)

    final_text = None

    if len(raw_text) > 100:
        logger.info("Спроба парсингу через AI.")
        final_text = await _extract_with_ai(raw_text)

    if not final_text:
        logger.info("AI не повернув результат. Використовую fallback-парсер.")
        final_text = _fallback_parse(soup)

    if not final_text or len(final_text.strip()) < MIN_ARTICLE_LENGTH:
        return "❌ Не вдалося знайти текст на цій сторінці."

    return clean_text_for_tts(final_text)


async def summarize_text_with_ai(text: str) -> str:
    """
    Створює короткий зміст великого тексту за допомогою AI.
    """
    if not text or len(text.strip()) < 50:
        return "❌ Недостатньо тексту для короткого змісту."

    if not ai_client:
        return "❌ Не вдалося створити короткий зміст: AI-клієнт недоступний."

    prompt = f"""
Ти — інструмент доступності для незрячих користувачів.
Зроби дуже стислий, але інформативний переказ тексту.
Максимум 3-4 речення.
Передай тільки головну суть.
Не використовуй вітань, вступів або Markdown.
Одразу переходь до суті.

ТЕКСТ:
{text[:MAX_RAW_TEXT_FOR_AI]}
"""

    try:
        response = await ai_client.aio.models.generate_content(
            model=AI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
            ),
        )

        result = _strip_ai_output(response.text or "")

        if not result:
            return "❌ Не вдалося створити короткий зміст."

        return result

    except Exception as e:
        logger.error("Помилка самаризації AI: %s", e)
        return "❌ Не вдалося створити короткий зміст через помилку сервера."