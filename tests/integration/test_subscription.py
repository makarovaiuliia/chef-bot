"""Заявки «хочу подписку»: одна на семью, идемпотентная кнопка."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.db import Family
from core.repositories import add_subscription_request, count_subscription_requests


async def _family(db_session) -> Family:
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    return fam


async def test_add_subscription_request_idempotent(db_session):
    fam = await _family(db_session)
    assert await add_subscription_request(
        db_session, family_id=fam.id, telegram_user_id=1
    ) is True
    assert await add_subscription_request(
        db_session, family_id=fam.id, telegram_user_id=2
    ) is False  # вторая заявка той же семьи не создается
    assert await count_subscription_requests(db_session) == 1


async def test_want_subscription_handler_notifies_superadmins(db_session, monkeypatch):
    from bot.handlers import subscription as sub_handler
    from config import get_settings

    monkeypatch.setattr(get_settings(), "superadmin_ids", [999])
    fam = await _family(db_session)
    cb = AsyncMock()
    cb.from_user = SimpleNamespace(id=1, full_name="Юля")

    await sub_handler.on_want_subscription(cb, fam, db_session)

    cb.answer.assert_awaited()
    sent_to = {call.args[0] for call in cb.bot.send_message.await_args_list}
    assert sent_to == {999}

    # повторный тап — вежливо, без второго уведомления
    cb2 = AsyncMock()
    cb2.from_user = SimpleNamespace(id=2, full_name="Вова")
    await sub_handler.on_want_subscription(cb2, fam, db_session)
    cb2.bot.send_message.assert_not_awaited()
