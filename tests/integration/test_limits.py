from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from config import get_settings
from core.db import Family, LlmUsage
from core.exceptions import MonthlyCapExceeded, TrialLimitExceeded
from core.repositories import log_llm_usage, sum_llm_tokens_current_month
from core.services import limits
from core.services.limits import ensure_within_limits

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
SUB_NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


async def _family(db_session) -> Family:
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    return fam


async def test_sum_tokens_counts_only_current_month(db_session):
    fam = await _family(db_session)
    await log_llm_usage(
        db_session, family_id=fam.id, operation="menu_gen", tokens_in=100, tokens_out=50
    )
    # запись прошлого месяца — с явной датой
    old = LlmUsage(
        family_id=fam.id, operation="menu_gen", tokens_in=999, tokens_out=999,
        created_at=NOW - timedelta(days=40),
    )
    db_session.add(old)
    await db_session.flush()
    total = await sum_llm_tokens_current_month(db_session, family_id=fam.id, now=NOW)
    assert total == 150


async def test_sum_includes_row_exactly_at_month_start(db_session):
    fam = await _family(db_session)
    await db_session.execute(sa.text(
        "INSERT INTO llm_usage (family_id, operation, tokens_in, tokens_out, created_at) "
        "VALUES (:f, 'menu_gen', 7, 7, '2026-07-01 00:00:00')"
    ), {"f": fam.id})
    total = await sum_llm_tokens_current_month(db_session, family_id=fam.id, now=NOW)
    assert total == 14


async def test_trial_limit_blocks_after_n_operations(db_session, monkeypatch):
    fam = await _family(db_session)
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 2)
    for _ in range(2):
        await log_llm_usage(
            db_session, family_id=fam.id, operation="menu_gen", tokens_in=1, tokens_out=1
        )
    with pytest.raises(TrialLimitExceeded) as exc_info:
        await limits.ensure_within_limits(
            db_session, family_id=fam.id, operation="menu_gen", now=NOW
        )
    assert exc_info.value.operation == "menu_gen"


async def test_trial_limits_are_per_operation(db_session, monkeypatch):
    fam = await _family(db_session)
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 1)
    await log_llm_usage(
        db_session, family_id=fam.id, operation="menu_gen", tokens_in=1, tokens_out=1
    )
    # replace не исчерпан — проходит
    await limits.ensure_within_limits(db_session, family_id=fam.id, operation="replace", now=NOW)


async def test_shopping_trial_limit_blocks_after_n_operations(db_session, monkeypatch):
    fam = await _family(db_session)
    monkeypatch.setattr(get_settings(), "trial_shopping_limit", 2)
    for _ in range(2):
        await log_llm_usage(
            db_session, family_id=fam.id, operation="shopping", tokens_in=1, tokens_out=1
        )
    with pytest.raises(TrialLimitExceeded) as exc_info:
        await limits.ensure_within_limits(
            db_session, family_id=fam.id, operation="shopping", now=NOW
        )
    assert exc_info.value.operation == "shopping"


async def test_shopping_hits_monthly_cap(db_session, monkeypatch):
    fam = await _family(db_session)
    monkeypatch.setattr(get_settings(), "monthly_token_cap_per_family", 100)
    await log_llm_usage(
        db_session, family_id=fam.id, operation="shopping", tokens_in=60, tokens_out=60
    )
    with pytest.raises(MonthlyCapExceeded):
        await limits.ensure_within_limits(
            db_session, family_id=fam.id, operation="shopping", now=NOW
        )


async def test_under_all_limits_passes(db_session):
    fam = await _family(db_session)
    await limits.ensure_within_limits(db_session, family_id=fam.id, operation="menu_gen", now=NOW)


def test_denial_texts():
    assert "лимит" in limits.denial_text(TrialLimitExceeded("menu_gen")).lower()
    assert "списков покупок" in limits.denial_text(TrialLimitExceeded("shopping"))
    assert "1-го числа" in limits.denial_text(MonthlyCapExceeded())


def test_denial_text_for_subscribed_cap():
    text = limits.denial_text(MonthlyCapExceeded(subscribed=True))
    assert "1-го числа" in text and "готовится" not in text


async def test_subscription_skips_trial_but_keeps_cap(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 0)
    fam = Family(name="f", sub_until=date(2026, 8, 21))
    db_session.add(fam)
    await db_session.flush()
    # триал нулевой, но подписка активна — операция проходит
    await ensure_within_limits(db_session, family_id=fam.id, operation="menu_gen", now=SUB_NOW)
    # подписочный потолок при этом работает
    monkeypatch.setattr(get_settings(), "sub_monthly_token_cap_per_family", 0)
    with pytest.raises(MonthlyCapExceeded) as e:
        await ensure_within_limits(db_session, family_id=fam.id, operation="menu_gen", now=SUB_NOW)
    assert e.value.subscribed is True


async def test_expired_subscription_back_to_trial(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 0)
    fam = Family(name="f", sub_until=date(2026, 7, 21))  # истекла вчера
    db_session.add(fam)
    await db_session.flush()
    with pytest.raises(TrialLimitExceeded):
        await ensure_within_limits(db_session, family_id=fam.id, operation="menu_gen", now=SUB_NOW)


async def test_extend_and_revoke_subscription(db_session):
    from core.repositories import extend_family_subscription, revoke_family_subscription

    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    today = date(2026, 7, 22)
    assert await extend_family_subscription(
        db_session, family_id=fam.id, days=30, today=today
    ) == date(2026, 8, 21)
    # повторный grant продлевает от текущего окончания, а не от today
    assert await extend_family_subscription(
        db_session, family_id=fam.id, days=30, today=today
    ) == date(2026, 9, 20)
    assert await revoke_family_subscription(db_session, family_id=fam.id) is True
    await db_session.refresh(fam)
    assert fam.sub_until is None
    assert await extend_family_subscription(
        db_session, family_id=999_999, days=30, today=today
    ) is None
