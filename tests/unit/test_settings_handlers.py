"""Хендлеры /settings: админ видит кнопки, участник — только текст."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import settings as settings_handler
from bot.keyboards import kb_settings
from core.db import MemberRole


def _family(**kw):
    defaults = dict(
        id=1, digest_enabled=True, digest_hour=9, timezone="Asia/Bangkok", sub_until=None
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _admin():
    return SimpleNamespace(role=MemberRole.admin, telegram_user_id=1)


def _member():
    return SimpleNamespace(role=MemberRole.member, telegram_user_id=2)


async def test_admin_sees_settings_with_buttons():
    message = AsyncMock()
    await settings_handler.cmd_settings(message, _family(), _admin())
    text = message.answer.await_args.args[0]
    assert "9:00" in text and "Asia/Bangkok" in text
    assert message.answer.await_args.kwargs["reply_markup"] is not None


async def test_member_sees_settings_without_buttons():
    message = AsyncMock()
    await settings_handler.cmd_settings(message, _family(), _member())
    assert message.answer.await_args.kwargs.get("reply_markup") is None


async def test_toggle_digest(monkeypatch):
    updated = {}

    async def fake_update(session, *, family, enabled=None, hour=None):
        updated["enabled"] = enabled
        return family

    monkeypatch.setattr(settings_handler, "update_digest_settings", fake_update)
    cb = AsyncMock()
    cb.data = "set:digest:off"
    await settings_handler.on_toggle_digest(cb, _family(), db_session=None)
    assert updated["enabled"] is False


async def test_set_hour_valid_updates_digest_and_view(monkeypatch):
    updated = {}

    async def fake_update(session, *, family, enabled=None, hour=None):
        updated["hour"] = hour
        family.digest_hour = hour
        return family

    monkeypatch.setattr(settings_handler, "update_digest_settings", fake_update)
    cb = AsyncMock()
    cb.data = "set:hour:8"
    fam = _family()
    await settings_handler.on_set_hour(cb, fam, db_session=None)
    assert updated["hour"] == 8
    text = cb.message.edit_text.await_args.args[0]
    assert "8:00" in text
    assert cb.message.edit_text.await_args.kwargs["reply_markup"] is not None


async def test_set_hour_out_of_range_shows_alert(monkeypatch):
    async def fake_update(session, *, family, enabled=None, hour=None):
        if hour is not None and not 5 <= hour <= 12:
            raise ValueError("out of range")
        return family

    monkeypatch.setattr(settings_handler, "update_digest_settings", fake_update)
    cb = AsyncMock()
    cb.data = "set:hour:99"
    await settings_handler.on_set_hour(cb, _family(), db_session=None)
    cb.answer.assert_awaited_once_with("Недоступный час", show_alert=True)


async def test_set_hour_forged_payload_shows_alert(monkeypatch):
    async def fake_update(session, *, family, enabled=None, hour=None):
        return family

    monkeypatch.setattr(settings_handler, "update_digest_settings", fake_update)
    cb = AsyncMock()
    cb.data = "set:hour:abc"
    await settings_handler.on_set_hour(cb, _family(), db_session=None)
    cb.answer.assert_awaited_once_with("Недоступный час", show_alert=True)


async def test_set_hour_same_value_is_noop(monkeypatch):
    fake_update = AsyncMock()
    monkeypatch.setattr(settings_handler, "update_digest_settings", fake_update)
    cb = AsyncMock()
    cb.data = "set:hour:9"
    await settings_handler.on_set_hour(cb, _family(digest_hour=9), db_session=None)
    cb.answer.assert_awaited_once_with("Уже установлено")
    cb.message.edit_text.assert_not_awaited()
    fake_update.assert_not_awaited()


async def test_toggle_digest_same_state_is_noop(monkeypatch):
    fake_update = AsyncMock()
    monkeypatch.setattr(settings_handler, "update_digest_settings", fake_update)
    cb = AsyncMock()
    cb.data = "set:digest:on"
    await settings_handler.on_toggle_digest(cb, _family(digest_enabled=True), db_session=None)
    cb.answer.assert_awaited_once_with()
    cb.message.edit_text.assert_not_awaited()
    fake_update.assert_not_awaited()


async def test_non_admin_set_callback_gets_alert():
    cb = AsyncMock()
    cb.data = "set:hour:9"
    await settings_handler.on_set_denied(cb)
    assert cb.answer.await_args.kwargs.get("show_alert") is True

    cb2 = AsyncMock()
    cb2.data = "set:tz"
    await settings_handler.on_set_denied(cb2)
    assert cb2.answer.await_args.kwargs.get("show_alert") is True


async def test_garbage_digest_suffix_alerts(monkeypatch):
    called = False

    async def fake_update(*a, **kw):
        nonlocal called
        called = True

    monkeypatch.setattr(settings_handler, "update_digest_settings", fake_update)
    cb = AsyncMock()
    cb.data = "set:digest:whatever"
    await settings_handler.on_toggle_digest(cb, _family(), db_session=None)
    assert called is False
    assert cb.answer.await_args.kwargs.get("show_alert") is True


def test_kb_settings_has_timezone_button():
    kb = kb_settings(_family())
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "set:tz" in datas


async def test_tz_button_sets_state_and_forcereplies():
    cb = AsyncMock()
    state = AsyncMock()
    await settings_handler.on_tz_button(cb, state)
    state.set_state.assert_awaited_once()
    text = cb.message.answer.await_args.args[0]
    assert "город" in text.lower()


async def test_tz_city_happy_saves_and_returns_kb_main(monkeypatch):
    async def fake_change(session, *, family, city, llm=None):
        return "Europe/Moscow"

    monkeypatch.setattr(settings_handler, "change_family_timezone", fake_change)
    message = AsyncMock()
    message.text = "Москва"
    state = AsyncMock()

    await settings_handler.on_tz_city(message, state, _family(), db_session=None)

    state.clear.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "Таймзона обновлена" in text and "Europe/Moscow" in text
    assert message.answer.await_args.kwargs.get("reply_markup") is not None


async def test_tz_city_unrecognized_keeps_state(monkeypatch):
    async def fake_change(session, *, family, city, llm=None):
        return None

    monkeypatch.setattr(settings_handler, "change_family_timezone", fake_change)
    message = AsyncMock()
    message.text = "асдфг"
    state = AsyncMock()

    await settings_handler.on_tz_city(message, state, _family(), db_session=None)

    state.clear.assert_not_awaited()  # состояние живо — можно написать другой город
    assert "Не узнал город" in message.answer.await_args.args[0]
    from aiogram.types import ForceReply

    assert isinstance(message.answer.await_args.kwargs.get("reply_markup"), ForceReply)


async def test_tz_city_llm_error_clears_state(monkeypatch):
    from core.exceptions import LLMError

    async def fake_change(session, *, family, city, llm=None):
        raise LLMError("boom")

    monkeypatch.setattr(settings_handler, "change_family_timezone", fake_change)
    message = AsyncMock()
    message.text = "Москва"
    state = AsyncMock()

    await settings_handler.on_tz_city(message, state, _family(), db_session=None)

    state.clear.assert_awaited_once()
    assert "Не получилось" in message.answer.await_args.args[0]


async def test_tz_city_cap_denial_with_subscription_kb(monkeypatch):
    from core.exceptions import MonthlyCapExceeded

    async def fake_change(session, *, family, city, llm=None):
        raise MonthlyCapExceeded()

    monkeypatch.setattr(settings_handler, "change_family_timezone", fake_change)
    message = AsyncMock()
    message.text = "Москва"
    state = AsyncMock()

    await settings_handler.on_tz_city(message, state, _family(), db_session=None)

    state.clear.assert_awaited_once()
    assert message.answer.await_args.kwargs.get("reply_markup") is not None  # kb подписки


async def test_tz_city_cap_denial_no_kb_with_active_subscription(monkeypatch):
    from datetime import date

    from core.exceptions import MonthlyCapExceeded

    async def fake_change(session, *, family, city, llm=None):
        raise MonthlyCapExceeded()

    monkeypatch.setattr(settings_handler, "change_family_timezone", fake_change)
    message = AsyncMock()
    message.text = "Москва"
    state = AsyncMock()

    await settings_handler.on_tz_city(
        message, state, _family(sub_until=date(2099, 1, 1)), db_session=None
    )

    state.clear.assert_awaited_once()
    assert message.answer.await_args.kwargs.get("reply_markup") is None


async def test_tz_city_non_text_prompts_again():
    message = AsyncMock()
    await settings_handler.on_tz_city_not_text(message)
    assert "текстом" in message.answer.await_args.args[0]


def test_tz_city_ignores_commands():
    """Хендлер on_tz_city не должен матчить команды — проверяем фильтр."""
    from tests.unit.test_button_handlers import _registered_filters

    filters_by_handler = dict(_registered_filters(settings_handler.router))
    on_tz = filters_by_handler["on_tz_city"]
    assert any("startswith" in f and "/" in f for f in on_tz)
