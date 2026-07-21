from datetime import date

from core.db import Family
from core.repositories import approve_menu, create_draft_menu, get_meal_for_family


async def test_get_meal_for_family_scopes_by_family(db_session):
    fam1, fam2 = Family(name="a"), Family(name="b")
    db_session.add_all([fam1, fam2])
    await db_session.flush()
    d = date(2026, 7, 21)
    menu = await create_draft_menu(
        db_session, family_id=fam1.id, start_date=d, days_count=1,
        meals=[{"date": d, "slot": "lunch", "dish_name": "О", "protein_kind": "chicken"}],
    )
    await approve_menu(db_session, menu.id)
    meal_id = menu.meals[0].id
    assert (await get_meal_for_family(db_session, meal_id, family_id=fam1.id)) is not None
    assert (await get_meal_for_family(db_session, meal_id, family_id=fam2.id)) is None
