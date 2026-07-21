from datetime import date

from core.db import Family, MealSlot
from core.repositories import approve_menu, create_draft_menu, get_meals_for_date


async def test_meals_for_date_ordered_breakfast_lunch_dinner(db_session):
    family = Family(name="f")
    db_session.add(family)
    await db_session.flush()
    d = date(2026, 7, 21)
    menu = await create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=d,
        days_count=1,
        meals=[
            {"date": d, "slot": "dinner", "dish_name": "У", "protein_kind": "beef"},
            {"date": d, "slot": "breakfast", "dish_name": "З", "protein_kind": "mixed"},
            {"date": d, "slot": "lunch", "dish_name": "О", "protein_kind": "chicken"},
        ],
    )
    await approve_menu(db_session, menu.id)
    meals = await get_meals_for_date(db_session, family.id, d)
    assert [m.slot for m in meals] == [MealSlot.breakfast, MealSlot.lunch, MealSlot.dinner]
