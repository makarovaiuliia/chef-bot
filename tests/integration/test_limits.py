from datetime import UTC, datetime, timedelta

import pytest

from config import get_settings
from core.db import Family, LlmUsage
from core.exceptions import MonthlyCapExceeded, TrialLimitExceeded
from core.repositories import log_llm_usage, sum_llm_tokens_current_month
from core.services import limits

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


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


async def test_shopping_has_no_trial_limit_but_hits_cap(db_session, monkeypatch):
    fam = await _family(db_session)
    monkeypatch.setattr(get_settings(), "monthly_token_cap_per_family", 100)
    await log_llm_usage(
        db_session, family_id=fam.id, operation="shopping", tokens_in=60, tokens_out=60
    )
    # триал для shopping не проверяется, но потолок — да
    with pytest.raises(MonthlyCapExceeded):
        await limits.ensure_within_limits(
            db_session, family_id=fam.id, operation="shopping", now=NOW
        )


async def test_under_all_limits_passes(db_session):
    fam = await _family(db_session)
    await limits.ensure_within_limits(db_session, family_id=fam.id, operation="menu_gen", now=NOW)


def test_denial_texts():
    assert "лимит" in limits.denial_text(TrialLimitExceeded("menu_gen")).lower()
    assert "1-го числа" in limits.denial_text(MonthlyCapExceeded())
