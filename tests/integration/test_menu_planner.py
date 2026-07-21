import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from core.constants import MENU_MAX_DAYS
from core.db import Family, Menu, MenuStatus
from core.exceptions import LLMInvalidResponse, MenuTooLong
from core.llm import LLMResponse
from core.repositories import count_llm_operations, get_future_meals
from core.services import menu_planner

START = date(2026, 7, 27)


class FakeLLM:
    def __init__(self, texts: list[str]):
        self._texts = list(texts)
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        return LLMResponse(text=self._texts.pop(0), tokens_in=100, tokens_out=200)


def _ok_menu(days: int = 3, start: date = START) -> str:
    meals = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        meals.append({"date": d, "slot": "lunch", "dish_name": f"Обед {i}",
                      "side_dishes": ["рис"], "protein_kind": "chicken"})
        meals.append({"date": d, "slot": "dinner", "dish_name": f"Ужин {i}",
                      "side_dishes": [], "protein_kind": "fish"})
    return json.dumps({"meals": meals})


async def _family(db_session) -> Family:
    fam = Family(name="f", profile_md="# Профиль", plan_slots=["lunch", "dinner"])
    db_session.add(fam)
    await db_session.flush()
    return fam


async def test_generate_menu_creates_draft(db_session):
    fam = await _family(db_session)
    menu = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    assert menu.status == MenuStatus.draft
    assert len(menu.meals) == 6
    assert await count_llm_operations(db_session, family_id=fam.id, operation="menu_gen") == 1
    # черновик не виден в активном календаре
    assert await get_future_meals(db_session, fam.id, START) == []


async def test_generate_menu_retries_once_then_fails(db_session):
    fam = await _family(db_session)
    llm = FakeLLM(["мусор", _ok_menu(3)])
    menu = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=llm
    )
    assert llm.calls == 2 and len(menu.meals) == 6

    llm2 = FakeLLM(["мусор", "мусор"])
    with pytest.raises(LLMInvalidResponse):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=START, days_count=3, llm=llm2
        )
    # неуспех не логируется: только одна запись от первой генерации
    assert await count_llm_operations(db_session, family_id=fam.id, operation="menu_gen") == 1


async def test_generate_menu_rejects_over_cap(db_session):
    fam = await _family(db_session)
    with pytest.raises(MenuTooLong):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=START,
            days_count=MENU_MAX_DAYS + 1, llm=FakeLLM([]),
        )


async def test_generate_menu_rejects_meals_outside_range(db_session):
    fam = await _family(db_session)
    bad = json.dumps({"meals": [{
        "date": "2026-09-01", "slot": "lunch", "dish_name": "Чужая дата",
        "side_dishes": [], "protein_kind": "chicken",
    }]})
    with pytest.raises(LLMInvalidResponse):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([bad, bad])
        )


async def test_approve_flow_with_conflicts(db_session):
    fam = await _family(db_session)
    first = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    assert await menu_planner.preview_approve(db_session, menu=first, today=START) == set()
    await menu_planner.commit_approve(db_session, menu=first, today=START)
    assert len(await get_future_meals(db_session, fam.id, START)) == 6

    second = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    conflicts = await menu_planner.preview_approve(db_session, menu=second, today=START)
    assert len(conflicts) == 3
    await menu_planner.commit_approve(db_session, menu=second, today=START)
    # старые meals на конфликтных датах удалены, осталось 6 новых
    assert len(await get_future_meals(db_session, fam.id, START)) == 6


async def test_menu_lives_until_its_end_menus_never_deleted(db_session):
    """Спека §7 (жизненный цикл): строки menus не удаляются никогда; при
    перезаписи страдают только meals на конфликтных датах — неперекрытые дни
    старого меню доживают до своего конца."""
    fam = await _family(db_session)
    first = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    await menu_planner.commit_approve(db_session, menu=first, today=START)

    # второе меню перекрывает только последний день первого (START+2)
    overlap_start = START + timedelta(days=2)
    second = await menu_planner.generate_menu(
        db_session, family=fam, start_date=overlap_start, days_count=3,
        llm=FakeLLM([_ok_menu(3, start=overlap_start)]),
    )
    await menu_planner.commit_approve(db_session, menu=second, today=START)

    meals = await get_future_meals(db_session, fam.id, START)
    # дни 0-1 первого меню (4 блюда) + 3 дня второго (6 блюд)
    assert len(meals) == 10
    menus = list(
        (await db_session.execute(select(Menu).where(Menu.family_id == fam.id)))
        .scalars()
        .all()
    )
    assert len(menus) == 2  # оба меню живы, ни одна строка menus не удалена


async def test_delete_draft_only_deletes_draft(db_session):
    fam = await _family(db_session)

    draft = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    await menu_planner.delete_draft(db_session, menu_id=draft.id)
    assert await db_session.get(Menu, draft.id) is None

    active = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    await menu_planner.commit_approve(db_session, menu=active, today=START)
    await menu_planner.delete_draft(db_session, menu_id=active.id)  # no-op: не draft
    reloaded = await db_session.get(Menu, active.id)
    assert reloaded is not None
    assert reloaded.status == MenuStatus.active

    await menu_planner.delete_draft(db_session, menu_id=999)  # no-op, не падает


def _incomplete_menu(days: int = 3, start: date = START) -> str:
    """Полное меню, кроме dinner на последний день (недостача одного слота)."""
    meals = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        meals.append({"date": d, "slot": "lunch", "dish_name": f"Обед {i}",
                      "side_dishes": ["рис"], "protein_kind": "chicken"})
        if i < days - 1:
            meals.append({"date": d, "slot": "dinner", "dish_name": f"Ужин {i}",
                          "side_dishes": [], "protein_kind": "fish"})
    return json.dumps({"meals": meals})


async def test_generate_menu_rejects_incomplete_menu(db_session):
    fam = await _family(db_session)
    incomplete = _incomplete_menu(3)
    with pytest.raises(LLMInvalidResponse):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=START, days_count=3,
            llm=FakeLLM([incomplete, incomplete]),
        )
    assert await count_llm_operations(db_session, family_id=fam.id, operation="menu_gen") == 0


async def test_generate_menu_rejects_duplicate_date_slot(db_session):
    fam = await _family(db_session)
    dup = json.dumps({"meals": [
        {"date": START.isoformat(), "slot": "lunch", "dish_name": "Обед 1",
         "side_dishes": [], "protein_kind": "chicken"},
        {"date": START.isoformat(), "slot": "lunch", "dish_name": "Обед 2",
         "side_dishes": [], "protein_kind": "fish"},
    ]})
    with pytest.raises(LLMInvalidResponse):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([dup, dup])
        )
    assert await count_llm_operations(db_session, family_id=fam.id, operation="menu_gen") == 0
