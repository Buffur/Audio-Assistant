from types import SimpleNamespace

from handlers import admin
from handlers import admin_menu
from handlers import catalog
from handlers import messages
from handlers import premium_admin
from handlers import reading_callbacks
from keyboards import admin_menu as admin_menu_keyboard
from keyboards import catalog as catalog_keyboard
from keyboards import privacy as privacy_keyboard
from keyboards import reading as reading_keyboard
from keyboards import settings as settings_keyboard
from services import reading_service
from texts import admin_menu as admin_menu_texts
from texts import catalog as catalog_texts
from texts import messages as message_texts
from texts import privacy as privacy_texts


def _message(text: str | None = None, user_id: int | None = None):
    from_user = None if user_id is None else SimpleNamespace(id=user_id)
    return SimpleNamespace(text=text, from_user=from_user)


def test_admin_command_text_and_target_parsing() -> None:
    assert admin._get_command_text(_message("/broadcast hello world"), "/broadcast") == "hello world"
    assert admin._get_command_text(_message("/broadcast"), "/broadcast") == ""

    assert admin._parse_target_user_id(_message("/ban 123")) == 123
    assert admin._parse_target_user_id(_message("/ban nope")) is None
    assert admin._parse_target_user_id(_message("/ban")) is None


def test_admin_broadcast_caption_is_limited() -> None:
    caption = admin._build_broadcast_caption("a" * 5000)

    assert len(caption) == admin.MAX_CAPTION_LENGTH
    assert caption.endswith("...")


def test_admin_broadcast_preview_is_limited_and_escaped() -> None:
    preview = admin._build_broadcast_preview_text("<b>" + "a" * 2000)

    assert "&lt;b&gt;" in preview
    assert "<b>aaaaaaaa" not in preview
    assert len(preview) < admin.MAX_BROADCAST_PREVIEW_LENGTH + 300
    assert preview.endswith(
        "і надішле його всім активним користувачам."
    )


def test_admin_checks_admin_ids(monkeypatch) -> None:
    monkeypatch.setattr(admin, "ADMIN_IDS", [10])

    assert admin._is_admin(_message(user_id=10)) is True
    assert admin._is_admin(_message(user_id=11)) is False
    assert admin._is_admin(_message()) is False


def test_premium_admin_parsers_and_admin_check(monkeypatch) -> None:
    monkeypatch.setattr(premium_admin, "ADMIN_IDS", [10])

    assert premium_admin._is_admin(_message(user_id=10)) is True
    assert premium_admin._is_admin(_message(user_id=11)) is False

    assert premium_admin._parse_user_id(_message("/premium 123 30")) == 123
    assert premium_admin._parse_user_id(_message("/premium nope 30")) is None
    assert premium_admin._parse_days(_message("/premium 123 30")) == 30
    assert premium_admin._parse_days(_message("/premium 123 nope")) is None


def test_admin_menu_admin_check(monkeypatch) -> None:
    monkeypatch.setattr(admin_menu, "ADMIN_IDS", [10])

    assert admin_menu._is_admin_user(10) is True
    assert admin_menu._is_admin_user(11) is False
    assert admin_menu._is_admin_user(None) is False


def test_admin_menu_detects_message_not_modified_error() -> None:
    assert admin_menu._is_message_not_modified_error(
        Exception("Bad Request: message is not modified")
    ) is True
    assert admin_menu._is_message_not_modified_error(
        Exception("Bad Request: chat not found")
    ) is False


def test_part_audio_caption_marks_internal_audio_chunks() -> None:
    assert message_texts.build_part_audio_caption(
        current_part=1,
        total_parts=2,
        current_audio=1,
        total_audio=2,
    ) == "📄 Частина 1 з 2 · аудіо 1 з 2"

    assert message_texts.build_part_audio_caption(
        current_part=1,
        total_parts=2,
        current_audio=1,
        total_audio=1,
    ) == "📄 Частина 1 з 2"


def test_reading_keyboard_adds_export_button_only_when_allowed() -> None:
    basic_keyboard = reading_keyboard.reading_navigation_keyboard(
        has_next=True,
        session_id="session-1",
    )
    premium_keyboard = reading_keyboard.reading_navigation_keyboard(
        has_next=True,
        session_id="session-1",
        can_export_audio=True,
    )

    basic_callbacks = [
        button.callback_data
        for row in basic_keyboard.inline_keyboard
        for button in row
    ]
    premium_callbacks = [
        button.callback_data
        for row in premium_keyboard.inline_keyboard
        for button in row
    ]
    export_callback = reading_keyboard.build_reading_callback(
        reading_keyboard.READ_EXPORT_AUDIO_ACTION,
        "session-1",
    )

    assert export_callback not in basic_callbacks
    assert export_callback in premium_callbacks


def test_reading_keyboard_can_hide_summary_button_after_summary_generated() -> None:
    navigation_keyboard = reading_keyboard.reading_navigation_keyboard(
        has_next=True,
        session_id="session-1",
        show_summary_button=False,
    )
    previous_voice_keyboard = reading_keyboard.summary_only_keyboard(
        session_id="session-1",
        show_summary_button=False,
    )

    callbacks = [
        button.callback_data
        for keyboard in (navigation_keyboard, previous_voice_keyboard)
        for row in keyboard.inline_keyboard
        for button in row
    ]
    summary_callback = reading_keyboard.build_reading_callback(
        reading_keyboard.READ_SUMMARY_ACTION,
        "session-1",
    )
    stop_callback = reading_keyboard.build_reading_callback(
        reading_keyboard.READ_STOP_ACTION,
        "session-1",
    )

    assert summary_callback not in callbacks
    assert stop_callback in callbacks


def test_summary_keyboard_does_not_offer_full_audio_export() -> None:
    keyboard = reading_keyboard.summary_navigation_keyboard(
        has_next=True,
        session_id="session-1",
        can_export_audio=True,
    )
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]
    export_callback = reading_keyboard.build_reading_callback(
        reading_keyboard.READ_EXPORT_AUDIO_ACTION,
        "session-1",
    )

    assert export_callback not in callbacks


def test_settings_keyboard_does_not_show_tts_provider_choice() -> None:
    keyboard = settings_keyboard.settings_keyboard()
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert all(not callback.startswith("tts_provider:") for callback in callbacks)
    assert settings_keyboard.SETTINGS_PREVIEW_CALLBACK in callbacks


def test_admin_menu_parses_user_callback_id() -> None:
    assert admin_menu._parse_user_id_from_callback(
        "admin_menu:user:123",
        "admin_menu:user:"
    ) == 123
    assert admin_menu._parse_user_id_from_callback(
        "admin_menu:user:nope",
        "admin_menu:user:"
    ) is None
    assert admin_menu._parse_user_id_from_callback(
        "admin_menu:other:123",
        "admin_menu:user:"
    ) is None


def test_admin_menu_parses_users_page_callback() -> None:
    assert admin_menu_keyboard.parse_admin_users_page_callback(
        "admin_menu:users_page:2"
    ) == 2
    assert admin_menu_keyboard.parse_admin_users_page_callback(
        "admin_menu:users_page:nope"
    ) is None
    assert admin_menu_keyboard.parse_admin_users_page_callback(
        "admin_menu:user:2"
    ) is None


def test_admin_menu_parses_limit_callbacks() -> None:
    assert admin_menu_keyboard.parse_admin_limit_name_callback(
        "admin_menu:limit_edit:text_messages_limit",
        "admin_menu:limit_edit:",
    ) == "text_messages_limit"
    assert admin_menu_keyboard.parse_admin_limit_name_callback(
        "admin_menu:limit_edit:",
        "admin_menu:limit_edit:",
    ) is None
    assert admin_menu_keyboard.parse_admin_limit_adjust_callback(
        "admin_menu:limit_adjust:text_messages_limit:-10"
    ) == ("text_messages_limit", -10)
    assert admin_menu_keyboard.parse_admin_limit_adjust_callback(
        "admin_menu:limit_adjust:text_messages_limit:nope"
    ) is None


def test_admin_menu_parses_user_action_callbacks() -> None:
    callback_data = admin_menu_keyboard.build_admin_user_action_callback(
        admin_menu_keyboard.ADMIN_MENU_USER_ACTION_CONFIRM_PREFIX,
        admin_menu_keyboard.ADMIN_USER_ACTION_BAN,
        123,
    )

    assert admin_menu_keyboard.parse_admin_user_action_callback(
        callback_data,
        admin_menu_keyboard.ADMIN_MENU_USER_ACTION_CONFIRM_PREFIX,
    ) == (admin_menu_keyboard.ADMIN_USER_ACTION_BAN, 123)
    assert admin_menu_keyboard.parse_admin_user_action_callback(
        "admin_menu:user_action_confirm:unknown:123",
        admin_menu_keyboard.ADMIN_MENU_USER_ACTION_CONFIRM_PREFIX,
    ) is None
    assert admin_menu_keyboard.parse_admin_user_action_callback(
        "admin_menu:user_action_confirm:ban:nope",
        admin_menu_keyboard.ADMIN_MENU_USER_ACTION_CONFIRM_PREFIX,
    ) is None

    reset_callback = admin_menu_keyboard.build_admin_user_action_callback(
        admin_menu_keyboard.ADMIN_MENU_USER_ACTION_PREFIX,
        admin_menu_keyboard.ADMIN_USER_ACTION_RESET_LIMITS,
        456,
    )
    assert admin_menu_keyboard.parse_admin_user_action_callback(
        reset_callback,
        admin_menu_keyboard.ADMIN_MENU_USER_ACTION_PREFIX,
    ) == (admin_menu_keyboard.ADMIN_USER_ACTION_RESET_LIMITS, 456)


def test_admin_user_action_buttons_use_confirmation_flow() -> None:
    keyboard = admin_menu_keyboard.admin_user_actions_keyboard(
        user_id=123,
        is_banned=False,
        is_limit_plus=True,
    )
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert any(
        callback.startswith(admin_menu_keyboard.ADMIN_MENU_USER_ACTION_PREFIX)
        for callback in callbacks
    )
    assert all(
        not callback.startswith(admin_menu_keyboard.ADMIN_MENU_USER_BAN_PREFIX)
        for callback in callbacks
    )
    assert any(
        callback.endswith(
            f"{admin_menu_keyboard.ADMIN_USER_ACTION_RESET_LIMITS}:123"
        )
        for callback in callbacks
    )

    confirm_keyboard = admin_menu_keyboard.admin_user_action_confirmation_keyboard(
        admin_menu_keyboard.ADMIN_USER_ACTION_BAN,
        123,
    )
    confirm_callbacks = [
        button.callback_data
        for row in confirm_keyboard.inline_keyboard
        for button in row
    ]

    assert confirm_callbacks[0].startswith(
        admin_menu_keyboard.ADMIN_MENU_USER_ACTION_CONFIRM_PREFIX
    )
    assert confirm_callbacks[1].startswith(
        admin_menu_keyboard.ADMIN_MENU_USER_ACTION_CANCEL_PREFIX
    )


def test_admin_user_detail_text_escapes_user_content() -> None:
    text = admin_menu_texts.build_admin_user_detail_text({
        "user_id": 1,
        "username": "<username>",
        "full_name": "<full>",
        "last_activity": "<date>",
        "is_banned": False,
        "plan": "free",
        "premium_until": None,
    })

    assert "&lt;username&gt;" in text
    assert "&lt;full&gt;" in text
    assert "&lt;date&gt;" in text
    assert "<username>" not in text


def test_admin_user_action_confirm_text_escapes_user_content() -> None:
    text = admin_menu_texts.build_admin_user_action_confirm_text(
        admin_menu_keyboard.ADMIN_USER_ACTION_BAN,
        {
            "user_id": 1,
            "username": "<username>",
            "full_name": "<full>",
        },
    )

    assert "&lt;username&gt;" in text
    assert "&lt;full&gt;" in text
    assert "<username>" not in text


def test_admin_users_text_shows_page_slice() -> None:
    users = [
        {
            "user_id": index,
            "username": f"user{index}",
            "full_name": f"User {index}",
            "last_activity": "today",
            "is_banned": False,
            "plan": "free",
        }
        for index in range(1, 13)
    ]

    text = admin_menu_texts.build_admin_users_text(
        users,
        page=1,
        page_size=10,
    )

    assert "Сторінка 2 з 2" in text
    assert "11. <b>User 11</b>" in text
    assert "1. <b>User 1</b>" not in text


def test_catalog_page_callbacks_and_text() -> None:
    assert catalog_keyboard.parse_catalog_page(
        "catalog_page:2",
        catalog_keyboard.CATALOG_PAGE_PREFIX,
    ) == 2
    assert catalog_keyboard.parse_catalog_page(
        "catalog_delete:123:4",
        catalog_keyboard.CATALOG_DELETE_PREFIX,
    ) == 4
    assert catalog_keyboard.parse_catalog_page(
        "catalog_delete:123",
        catalog_keyboard.CATALOG_DELETE_PREFIX,
    ) is None

    text = catalog_texts.build_catalog_text(
        [
            {
                "source_type": "text",
                "source_name": "Doc",
                "text_length": 10,
                "chunks_count": 1,
                "created_at": "today",
                "text_preview": "preview",
                "has_chunks": True,
            }
        ],
        page=1,
        total_pages=3,
        total_items=11,
        page_size=5,
    )

    assert "Сторінка 2 з 3" in text
    assert "<b>6. Текст</b>" in text
    assert "📖 10 символів · 🎧 1 частин" in text


def test_delete_my_data_confirmation_keyboard_and_text() -> None:
    keyboard = privacy_keyboard.delete_my_data_confirmation_keyboard(user_id=123)
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]

    confirm_callback = privacy_keyboard.build_delete_my_data_confirm_callback(123)
    cancel_callback = privacy_keyboard.build_delete_my_data_cancel_callback(123)

    assert confirm_callback in callbacks
    assert cancel_callback in callbacks
    assert privacy_keyboard.parse_delete_my_data_callback_user_id(confirm_callback) == 123
    assert privacy_keyboard.parse_delete_my_data_callback_user_id(cancel_callback) == 123
    assert "Підтвердьте очищення даних" in privacy_texts.DELETE_MY_DATA_CONFIRM_TEXT
    assert "історію документів" in privacy_texts.DELETE_MY_DATA_CONFIRM_TEXT
    assert "Денні лічильники використання" in privacy_texts.DELETE_MY_DATA_CONFIRM_TEXT
    assert "не видаляються" in privacy_texts.DELETE_MY_DATA_CONFIRM_TEXT


def test_catalog_reading_session_restores_cached_summary() -> None:
    session = reading_service.create_reading_session(
        chunks=["one", "two"],
        catalog_document_id=42,
        summary_text="Cached summary",
        summary_voice_file_ids=["voice-file-id"],
        summary_voice_voice="uk-UA-PolinaNeural",
        summary_voice_rate="+0%",
        summary_voice_provider="edge",
    )

    assert session["catalog_document_id"] == 42
    assert session["chunks"] == ["one", "two"]
    assert session["summary_text"] == "Cached summary"
    assert session["summary_delivered"] is False
    assert session["summary_voice_file_ids"] == ["voice-file-id"]
    assert session["summary_voice_voice"] == "uk-UA-PolinaNeural"


def test_messages_limit_extracted_text() -> None:
    short_text = "hello"
    assert messages._limit_extracted_text(short_text) == (short_text, False)

    long_text = "a" * (messages.MAX_EXTRACTED_TEXT_LENGTH + 10)
    limited_text, was_limited = messages._limit_extracted_text(long_text)

    assert len(limited_text) == messages.MAX_EXTRACTED_TEXT_LENGTH
    assert was_limited is True


def test_messages_supported_processing_detection() -> None:
    assert messages._is_supported_processing_message(
        SimpleNamespace(text="hello", photo=None, document=None)
    ) is True
    assert messages._is_supported_processing_message(
        SimpleNamespace(text=None, photo=[object()], document=None)
    ) is True
    assert messages._is_supported_processing_message(
        SimpleNamespace(text=None, photo=None, document=object())
    ) is True
    assert messages._is_supported_processing_message(
        SimpleNamespace(text=None, photo=None, document=None, sticker=object())
    ) is False


def test_messages_unsupported_warning_cooldown() -> None:
    messages._last_unsupported_message_warning_time.clear()

    assert messages._can_send_unsupported_message_warning(1, 100.0) is True
    assert messages._can_send_unsupported_message_warning(1, 110.0) is False
    assert messages._can_send_unsupported_message_warning(
        1,
        100.0 + messages.UNSUPPORTED_MESSAGE_WARNING_COOLDOWN_SECONDS,
    ) is True


def test_messages_user_processing_lock_lifecycle() -> None:
    messages._user_processing_locks.clear()
    messages._user_processing_lock_usage.clear()

    first_lock = messages._reserve_user_processing_lock(1)
    second_lock = messages._reserve_user_processing_lock(1)

    assert first_lock is second_lock
    assert messages._user_processing_lock_usage[1] == 2

    messages._release_user_processing_lock(1)
    assert messages._user_processing_lock_usage[1] == 1

    messages._release_user_processing_lock(1)
    assert 1 not in messages._user_processing_lock_usage
    assert 1 not in messages._user_processing_locks


def test_reading_callback_session_matching() -> None:
    session = {"session_id": "current"}

    assert reading_callbacks._is_matching_session(session, None) is True
    assert reading_callbacks._is_matching_session(session, "current") is True
    assert reading_callbacks._is_matching_session(session, "old") is False


def test_reading_callback_catalog_document_id_parsing() -> None:
    assert reading_callbacks._get_catalog_document_id(
        1,
        {"catalog_document_id": "42"},
    ) == 42
    assert reading_callbacks._get_catalog_document_id(
        1,
        {"catalog_document_id": None},
    ) is None
    assert reading_callbacks._get_catalog_document_id(
        1,
        {"catalog_document_id": "invalid"},
    ) is None
