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
    assert "уже в списке" in cb2.answer.await_args.args[0]


async def test_add_subscription_request_manual_insert_returns_false(db_session):
    """Строка уже вставлена в обход репозитория (не через add_subscription_request) —
    select-фаст-путь должен ее увидеть и вернуть False без исключения."""
    from core.db import SubscriptionRequest

    fam = await _family(db_session)
    db_session.add(SubscriptionRequest(family_id=fam.id, telegram_user_id=1))
    await db_session.flush()

    assert await add_subscription_request(
        db_session, family_id=fam.id, telegram_user_id=2
    ) is False
    assert await count_subscription_requests(db_session) == 1


async def test_add_subscription_request_race_swallows_integrity_error(
    db_session, monkeypatch
):
    """Гонка двух одновременных тапов: оба select видят пустую таблицу (второй
    select смоделирован так, будто вставка первого еще не наблюдаема), но
    проигравший insert должен поймать IntegrityError на savepoint и вернуть
    False, а не упасть необработанным исключением наружу."""
    fam = await _family(db_session)

    orig_execute = db_session.execute
    calls = {"n": 0}

    async def fake_execute(stmt, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            class _EmptyResult:
                def scalar_one_or_none(self):
                    return None

            return _EmptyResult()
        return await orig_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", fake_execute)

    first = await add_subscription_request(db_session, family_id=fam.id, telegram_user_id=1)
    second = await add_subscription_request(db_session, family_id=fam.id, telegram_user_id=2)

    assert first is True
    assert second is False  # IntegrityError на savepoint поймана, не пробросилась
    assert await count_subscription_requests(db_session) == 1
