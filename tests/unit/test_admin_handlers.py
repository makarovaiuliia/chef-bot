"""Хендлер /admin: сводка форматируется и отправляется."""
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
