# Файл: tests/test_splitter.py

from utils.splitter import MAX_LENGTH, split_text


def test_split_text_returns_empty_list_for_empty_text():
    assert split_text("") == []


def test_split_text_returns_single_chunk_for_short_text():
    text = "Це короткий текст для перевірки."

    chunks = split_text(text)

    assert len(chunks) == 1
    assert chunks[0] == text


def test_split_text_preserves_all_words_for_regular_text():
    text = "Перший абзац.\nДругий абзац.\nТретій абзац."

    chunks = split_text(text)
    result_text = "\n".join(chunks)

    assert "Перший абзац." in result_text
    assert "Другий абзац." in result_text
    assert "Третій абзац." in result_text


def test_split_text_does_not_create_empty_chunks():
    text = "\n\nПерший абзац.\n\n\nДругий абзац.\n\n"

    chunks = split_text(text)

    assert chunks
    assert all(chunk.strip() for chunk in chunks)


def test_split_text_chunks_do_not_exceed_max_length_for_long_text():
    text = ("Це тестове речення. " * 1000).strip()

    chunks = split_text(text)

    assert chunks
    assert all(len(chunk) <= MAX_LENGTH for chunk in chunks)


def test_split_text_splits_very_long_word_safely():
    long_word = "а" * (MAX_LENGTH * 2 + 100)

    chunks = split_text(long_word)

    assert chunks
    assert all(len(chunk) <= MAX_LENGTH for chunk in chunks)
    assert "".join(chunk.replace(" ", "") for chunk in chunks) == long_word


def test_split_text_handles_mixed_paragraphs_and_long_word():
    long_word = "b" * (MAX_LENGTH + 50)
    text = f"Початок тексту.\n{long_word}\nКінець тексту."

    chunks = split_text(text)

    assert chunks
    assert all(len(chunk) <= MAX_LENGTH for chunk in chunks)

    result_text = "".join(chunk.replace("\n", "").replace(" ", "") for chunk in chunks)

    assert "Початоктексту." in result_text
    assert long_word in result_text
    assert "Кінецьтексту." in result_text