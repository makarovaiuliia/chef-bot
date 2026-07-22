"""Хендлеры /settings: админ видит кнопки, участник — только текст."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import settings as settings_handler
from core.db import MemberRole


def _family(**kw):
    defaults = dict(id=1, digest_enabled=True, digest_hour=9, timezone="Asia/Bangkok")
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
