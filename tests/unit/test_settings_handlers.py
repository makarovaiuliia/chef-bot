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
