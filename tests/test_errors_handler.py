from types import SimpleNamespace

import pytest

from handlers import errors
from services import runtime_state
from texts.messages import GENERIC_INTERNAL_ERROR_TEXT


class FakeCallbackQuery:
    def __init__(self) -> None:
        self.data = "catalog:delete:123"
        self.from_user = SimpleNamespace(id=7)
        self.message = SimpleNamespace(
            message_id=42,
            chat=SimpleNamespace(id=1001),
            from_user=SimpleNamespace(id=7),
        )
        self.answers = []

    async def answer(self, text, show_alert=False):
        self.answers.append({
            "text": text,
            "show_alert": show_alert,
        })


def test_build_error_context_uses_safe_callback_metadata() -> None:
    callback = FakeCallbackQuery()
    event = SimpleNamespace(
        exception=RuntimeError("boom"),
        update=SimpleNamespace(
            update_id=55,
            callback_query=callback,
            message=None,
        ),
    )

    context = errors._build_error_context(event)

    assert context["telegram_update_id"] == 55
    assert context["telegram_update_type"] == "callback_query"
    assert context["telegram_user_id"] == 7
    assert context["telegram_chat_id"] == 1001
    assert context["telegram_message_id"] == 42
    assert context["telegram_callback_prefix"] == "catalog"
    assert context["telegram_callback_data_length"] == len(callback.data)


@pytest.mark.asyncio
async def test_global_error_handler_records_metric_and_notifies_callback(
    monkeypatch,
) -> None:
    runtime_state.reset_runtime_state()
    metrics = []

    async def fake_record_service_metric(**kwargs):
        metrics.append(kwargs)

    monkeypatch.setattr(errors, "record_service_metric", fake_record_service_metric)

    callback = FakeCallbackQuery()
    event = SimpleNamespace(
        exception=RuntimeError("boom"),
        update=SimpleNamespace(
            update_id=55,
            callback_query=callback,
            message=None,
        ),
    )

    result = await errors.global_error_handler(event)
    health = runtime_state.get_runtime_health(now=10**12)

    assert result is True
    assert callback.answers == [{
        "text": GENERIC_INTERNAL_ERROR_TEXT,
        "show_alert": True,
    }]
    assert metrics[0]["provider"] == "bot"
    assert metrics[0]["operation"] == "update_handler"
    assert metrics[0]["success"] is False
    assert health["components"][0]["component"] == "telegram_update"

    runtime_state.reset_runtime_state()
