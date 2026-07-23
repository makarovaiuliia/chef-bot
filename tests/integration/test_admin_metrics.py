"""Метрики /admin: сводка за календарный месяц и обзор семей."""
from datetime import UTC, date, datetime

from core.db import Family, FamilyMember, MemberRole
from core.repositories import (
    admin_month_summary,
    families_overview,
    log_llm_usage,
)

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


async def test_admin_month_summary(db_session):
    fam1, fam2 = Family(name="a"), Family(name="b")
    db_session.add_all([fam1, fam2])
    await db_session.flush()
    await log_llm_usage(db_session, family_id=fam1.id, operation="menu_gen",
                        tokens_in=100, tokens_out=200)
    await log_llm_usage(db_session, family_id=fam2.id, operation="recipe",
                        tokens_in=10, tokens_out=20)

    s = await admin_month_summary(db_session, now=NOW)

    assert s["families"] == 2
    assert s["ops"] == {"menu_gen": 1, "recipe": 1}
    assert s["tokens_in"] == 110 and s["tokens_out"] == 220


async def test_families_overview(db_session):
    fam = Family(name="a", timezone="Asia/Bangkok")
    fam2 = Family(name="b", timezone="UTC", sub_until=date(2026, 8, 21))
    db_session.add_all([fam, fam2])
    await db_session.flush()
    db_session.add(FamilyMember(family_id=fam.id, telegram_user_id=1,
                                role=MemberRole.admin))
    db_session.add(FamilyMember(family_id=fam.id, telegram_user_id=2,
                                role=MemberRole.member))
    await db_session.flush()
    await log_llm_usage(db_session, family_id=fam.id, operation="menu_gen",
                        tokens_in=5, tokens_out=7)
    await log_llm_usage(db_session, family_id=fam.id, operation="recipe",
                        tokens_in=3, tokens_out=4)

    rows = await families_overview(db_session, now=NOW)

    assert rows[0]["id"] == fam.id
    assert rows[0]["members"] == 2
    assert rows[0]["tokens_month"] == 19
    assert rows[0]["sub_until"] is None
    assert rows[1]["sub_until"] == date(2026, 8, 21)
