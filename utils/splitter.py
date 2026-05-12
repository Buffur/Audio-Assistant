# Файл: utils/splitter.py

MAX_LENGTH = 3000
PARAGRAPH_SEPARATOR = "\n\n"


def _append_chunk(chunks: list[str], chunk: str) -> None:
    """
    Додає chunk у список, якщо він не порожній.

    Це захищає від випадкового створення порожніх частин,
    які потім могли б піти в TTS.
    """
    clean_chunk = chunk.strip()

    if clean_chunk:
        chunks.append(clean_chunk)


def _split_long_word(word: str, max_length: int) -> list[str]:
    """
    Розбиває дуже довге слово або рядок без пробілів на частини.

    Наприклад, це може бути:
    - довге посилання;
    - base64-подібний текст;
    - технічний рядок без пробілів.
    """
    return [
        word[index:index + max_length]
        for index in range(0, len(word), max_length)
    ]


def _add_word_to_chunk(
    chunks: list[str],
    current_chunk: str,
    word: str,
    max_length: int
) -> str:
    """
    Додає слово до поточного chunk.

    Якщо слово не вміщується:
    - поточний chunk зберігається;
    - слово починає новий chunk.

    Якщо саме слово довше за max_length:
    - воно розбивається на безпечні частини.
    """
    if not word:
        return current_chunk

    if len(word) > max_length:
        _append_chunk(chunks, current_chunk)
        current_chunk = ""

        word_parts = _split_long_word(word, max_length)

        for part in word_parts[:-1]:
            _append_chunk(chunks, part)

        return word_parts[-1] + " " if word_parts else ""

    if len(current_chunk) + len(word) + 1 > max_length:
        _append_chunk(chunks, current_chunk)
        return word + " "

    return current_chunk + word + " "


def split_text(text: str) -> list[str]:
    """
    Розбиває текст на фрагменти, не розриваючи слова та абзаци.

    Основна мета:
    - не перевищувати MAX_LENGTH;
    - зберігати логічні паузи між абзацами;
    - не створювати порожні частини;
    - безпечно обробляти дуже довгі слова або рядки без пробілів.
    """
    if not text:
        return []

    paragraphs = text.split("\n")
    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:
        paragraph = paragraph.strip()

        if not paragraph:
            continue

        if len(paragraph) > MAX_LENGTH:
            words = paragraph.split(" ")

            for word in words:
                current_chunk = _add_word_to_chunk(
                    chunks=chunks,
                    current_chunk=current_chunk,
                    word=word,
                    max_length=MAX_LENGTH
                )

            continue

        paragraph_with_separator = paragraph + PARAGRAPH_SEPARATOR

        if len(current_chunk) + len(paragraph_with_separator) > MAX_LENGTH:
            _append_chunk(chunks, current_chunk)
            current_chunk = paragraph_with_separator
        else:
            current_chunk += paragraph_with_separator

    _append_chunk(chunks, current_chunk)

    return chunks