"""Сервисы проверяют лимиты ДО вызова LLM (LLM не дергается при отказе)."""
from datetime import date

import pytest

from config import get_settings
from core.db import Family
from core.exceptions import MonthlyCapExceeded, TrialLimitExceeded
from core.repositories import log_llm_usage
from core.services import menu_planner


class ExplodingLLM:
    """LLM, который не должен быть вызван."""

    async def chat(self, **kwargs):
        raise AssertionError("LLM вызван несмотря на исчерпанный лимит")


async def test_generate_menu_blocked_by_trial(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 1)
    fam = Family(name="f", profile_md="п", plan_slots=["lunch", "dinner"])
    db_session.add(fam)
    await db_session.flush()
    await log_llm_usage(
        db_session, family_id=fam.id, operation="menu_gen", tokens_in=1, tokens_out=1
    )
    with pytest.raises(TrialLimitExceeded):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=date(2026, 7, 27),
            days_count=3, llm=ExplodingLLM(),
        )


async def test_generate_menu_blocked_by_cap(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "monthly_token_cap_per_family", 10)
    fam = Family(name="f", profile_md="п", plan_slots=["lunch", "dinner"])
    db_session.add(fam)
    await db_session.flush()
    await log_llm_usage(
        db_session, family_id=fam.id, operation="recipe", tokens_in=6, tokens_out=6
    )
    with pytest.raises(MonthlyCapExceeded):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=date(2026, 7, 27),
            days_count=3, llm=ExplodingLLM(),
        )
