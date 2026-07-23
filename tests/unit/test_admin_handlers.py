"""Хендлер /admin: сводка форматируется и отправляется."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import admin as admin_handler


async def test_cmd_admin_sends_summary(monkeypatch):
    async def fake_summary(session, *, now):
        return {"families": 3, "ops": {"menu_gen": 5, "recipe": 2},
                "tokens_in": 1_000_000, "tokens_out": 200_000}

    async def fake_overview(session, *, now):
        return [{"id": 1, "name": "Тест", "members": 2,
                 "timezone": "UTC", "tokens_month": 500}]

    async def fake_requests(session):
        return 1

    monkeypatch.setattr(admin_handler.repositories, "admin_month_summary", fake_summary)
    monkeypatch.setattr(admin_handler.repositories, "families_overview", fake_overview)
    monkeypatch.setattr(
        admin_handler.repositories, "count_subscription_requests", fake_requests
    )
    message = AsyncMock()

    await admin_handler.cmd_admin(message, db_session=None)

    text = message.answer.await_args.args[0]
    assert "Семей: 3" in text and "menu_gen: 5" in text and "Тест" in text
    assert "$" in text  # оценка стоимости присутствует


async def test_cmd_grant_activates_and_notifies_admins(monkeypatch):
    calls = {}

    async def fake_extend(session, *, family_id, days, today):
        calls["args"] = (family_id, days)
        return date(2026, 8, 21)

    async def fake_admins(session, *, family_id):
        return [SimpleNamespace(telegram_user_id=111)]

    monkeypatch.setattr(
        admin_handler.repositories, "extend_family_subscription", fake_extend
    )
    monkeypatch.setattr(admin_handler, "get_admins", fake_admins)
    message = AsyncMock()
    message.text = "/grant 7"

    await admin_handler.cmd_grant(message, db_session=None)

    assert calls["args"] == (7, 30)
    message.bot.send_message.assert_awaited()  # уведомление админам семьи
    assert "21.08.2026" in message.answer.await_args.args[0]


async def test_cmd_grant_custom_days(monkeypatch):
    calls = {}

    async def fake_extend(session, *, family_id, days, today):
        calls["args"] = (family_id, days)
        return date(2026, 10, 20)

    async def fake_admins(session, *, family_id):
        return []

    monkeypatch.setattr(
        admin_handler.repositories, "extend_family_subscription", fake_extend
    )
    monkeypatch.setattr(admin_handler, "get_admins", fake_admins)
    message = AsyncMock()
    message.text = "/grant 7 90"

    await admin_handler.cmd_grant(message, db_session=None)

    assert calls["args"] == (7, 90)


async def test_cmd_grant_bad_arg_shows_usage():
    message = AsyncMock()
    message.text = "/grant abc"
    await admin_handler.cmd_grant(message, db_session=None)
    assert "/grant" in message.answer.await_args.args[0]


async def test_cmd_revoke_resets_subscription(monkeypatch):
    calls = {}

    async def fake_revoke(session, *, family_id):
        calls["family_id"] = family_id
        return True

    monkeypatch.setattr(
        admin_handler.repositories, "revoke_family_subscription", fake_revoke
    )
    message = AsyncMock()
    message.text = "/revoke 7"

    await admin_handler.cmd_revoke(message, db_session=None)

    assert calls["family_id"] == 7
