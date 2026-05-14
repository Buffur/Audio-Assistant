from services import ollama_ai


def test_strip_ollama_output_removes_thinking_and_markdown() -> None:
    text = ollama_ai._strip_ollama_output(
        "<think>internal reasoning</think>\n```text\nГотовий текст\n```"
    )

    assert text == "Готовий текст"
