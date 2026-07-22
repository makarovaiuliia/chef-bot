from datetime import date, timedelta

from core.db import Family
from core.repositories import approve_menu, create_draft_menu
from core.services import reminders, shopping_list
from core.services.family_service import create_family
from core.services.reminders import plan_reminder_due


async def test_reminder_none_when_empty(db_session):
    family, _ = await create_family(
        db_session,
        telegram_user_id=111,
        display_name=None,
        profile_md="тестовый профиль",
        timezone="UTC",
        plan_slots=["lunch", "dinner"],
    )
    text = await reminders.build_shopping_reminder(db_session, family_id=family.id)
    assert text is None


async def test_reminder_counts_open_items(db_session):
    family, _ = await create_family(
        db_session,
        telegram_user_id=111,
        display_name=None,
        profile_md="тестовый профиль",
        timezone="UTC",
        plan_slots=["lunch", "dinner"],
    )
    for name in ["молоко", "хлеб", "сыр"]:
        await shopping_list.add_manual_item(db_session, family_id=family.id, name=name)

    text = await reminders.build_shopping_reminder(db_session, family_id=family.id)

    assert text is not None
    assert "3" in text
    assert "/list" in text


async def test_reminder_skips_bought_items(db_session):
    family, _ = await create_family(
        db_session,
        telegram_user_id=111,
        display_name=None,
        profile_md="тестовый профиль",
        timezone="UTC",
        plan_slots=["lunch", "dinner"],
    )
    items = [
        await shopping_list.add_manual_item(db_session, family_id=family.id, name=n)
        for n in ["молоко", "хлеб"]
    ]
    await shopping_list.toggle_bought(
        db_session, item_id=items[0].id, family_id=family.id
    )

    text = await reminders.build_shopping_reminder(db_session, family_id=family.id)

    assert text == "🛒 В списке покупок 1 пункт → /list"


async def test_plan_reminder_due_exactly_two_days_before_end(db_session):
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    today = date(2026, 7, 21)
    menu = await create_draft_menu(
        db_session, family_id=fam.id, start_date=today, days_count=3,
        meals=[
            {"date": today + timedelta(days=i), "slot": "dinner",
             "dish_name": f"Д{i}", "protein_kind": "chicken"}
            for i in range(3)  # последняя дата = today + 2
        ],
    )
    await approve_menu(db_session, menu.id)
    assert await plan_reminder_due(db_session, family_id=fam.id, today=today) is True
    assert await plan_reminder_due(
        db_session, family_id=fam.id, today=today - timedelta(days=1)
    ) is False  # осталось 3 дня
    assert await plan_reminder_due(
        db_session, family_id=fam.id, today=today + timedelta(days=1)
    ) is False  # остался 1 день


async def test_plan_reminder_not_due_without_menu(db_session):
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    assert await plan_reminder_due(db_session, family_id=fam.id, today=date(2026, 7, 21)) is False
