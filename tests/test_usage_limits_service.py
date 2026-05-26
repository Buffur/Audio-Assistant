from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services import usage_limits_service as service


def _message(
    *,
    text=None,
    document=None,
    photo=None,
):
    return SimpleNamespace(text=text, document=document, photo=photo)


def test_detect_input_usage_type() -> None:
    image_document = SimpleNamespace(mime_type="image/png")
    pdf_document = SimpleNamespace(mime_type="application/pdf")

    assert service.detect_input_usage_type(_message(photo=[object()])) == service.USAGE_TYPE_OCR
    assert service.detect_input_usage_type(_message(document=image_document)) == service.USAGE_TYPE_OCR
    assert service.detect_input_usage_type(_message(document=pdf_document)) == service.USAGE_TYPE_FILE
    assert service.detect_input_usage_type(_message(text="https://example.com")) == service.USAGE_TYPE_LINK
    assert service.detect_input_usage_type(_message(text="hello")) == service.USAGE_TYPE_TEXT


def test_parse_datetime_handles_invalid_values() -> None:
    assert service._parse_datetime(None) is None
    assert service._parse_datetime("not a date") is None
    assert service._parse_datetime("2026-05-13T12:00:00") == datetime(2026, 5, 13, 12, 0, 0)


def test_parse_limit_value_falls_back_to_default() -> None:
    assert service._parse_limit_value(None, 10) == 10
    assert service._parse_limit_value("bad", 10) == 10
    assert service._parse_limit_value("0", 10) == 1
    assert service._parse_limit_value("7", 10) == 7


@pytest.mark.asyncio
async def test_is_premium_user_for_admin(monkeypatch) -> None:
    monkeypatch.setattr(service, "ADMIN_IDS", [1])

    assert await service.is_premium_user(1) is True


@pytest.mark.asyncio
async def test_is_premium_user_for_active_and_expired_plan(monkeypatch) -> None:
    async def active_plan(user_id):
        return {
            "plan": "premium",
            "premium_until": (datetime.now() + timedelta(days=1)).isoformat(),
        }

    async def expired_plan(user_id):
        return {
            "plan": "premium",
            "premium_until": (datetime.now() - timedelta(days=1)).isoformat(),
        }

    monkeypatch.setattr(service, "ADMIN_IDS", [])
    monkeypatch.setattr(service, "get_user_plan_info", active_plan)
    assert await service.is_premium_user(10) is True

    monkeypatch.setattr(service, "get_user_plan_info", expired_plan)
    assert await service.is_premium_user(10) is False


@pytest.mark.asyncio
async def test_reserve_input_processing_uses_atomic_db_helper(monkeypatch) -> None:
    captured = {}

    async def fake_is_premium_user(user_id):
        return False

    async def fake_try_increment_daily_usage_under_limit(**kwargs):
        captured.update(kwargs)
        return True

    async def fake_get_editable_limits():
        return service.DEFAULT_LIMITS

    monkeypatch.setattr(service, "is_premium_user", fake_is_premium_user)
    monkeypatch.setattr(
        service,
        "get_editable_limits",
        fake_get_editable_limits,
    )
    monkeypatch.setattr(
        service,
        "try_increment_daily_usage_under_limit",
        fake_try_increment_daily_usage_under_limit,
    )

    assert await service.reserve_input_processing(1, service.USAGE_TYPE_LINK) is True
    assert captured["field_name"] == service.USAGE_FIELD_LINKS
    assert captured["limit"] == service.FREE_DAILY_LINK_LIMIT


@pytest.mark.asyncio
async def test_reserve_input_processing_records_premium_usage(monkeypatch) -> None:
    captured = {}

    async def fake_is_premium_user(user_id):
        return True

    async def fake_increment_daily_usage(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(service, "is_premium_user", fake_is_premium_user)
    monkeypatch.setattr(service, "increment_daily_usage", fake_increment_daily_usage)

    assert await service.reserve_input_processing(1, service.USAGE_TYPE_OCR) is True
    assert captured["field_name"] == service.USAGE_FIELD_OCR


@pytest.mark.asyncio
async def test_refund_input_processing_decrements_reserved_usage(monkeypatch) -> None:
    captured = {}

    async def fake_decrement_daily_usage(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(service, "_today_key", lambda: "2026-05-20")
    monkeypatch.setattr(service, "decrement_daily_usage", fake_decrement_daily_usage)

    await service.refund_input_processing(123, service.USAGE_TYPE_FILE)

    assert captured == {
        "user_id": 123,
        "usage_date": "2026-05-20",
        "field_name": service.USAGE_FIELD_FILES,
    }


@pytest.mark.asyncio
async def test_refund_summary_generation_decrements_reserved_usage(monkeypatch) -> None:
    captured = {}

    async def fake_decrement_daily_usage(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(service, "_today_key", lambda: "2026-05-20")
    monkeypatch.setattr(service, "decrement_daily_usage", fake_decrement_daily_usage)

    await service.refund_summary_generation(123)

    assert captured == {
        "user_id": 123,
        "usage_date": "2026-05-20",
        "field_name": service.USAGE_FIELD_SUMMARIES,
    }


@pytest.mark.asyncio
async def test_reset_user_daily_limits_uses_today_key(monkeypatch) -> None:
    captured = {}

    async def fake_reset_daily_usage(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(service, "_today_key", lambda: "2026-05-19")
    monkeypatch.setattr(service, "reset_daily_usage", fake_reset_daily_usage)

    assert await service.reset_user_daily_limits(123) is True
    assert captured == {
        "user_id": 123,
        "usage_date": "2026-05-19",
    }
