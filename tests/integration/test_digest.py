from datetime import date

from core import repositories
from core.services import digest
from core.services.family_service import get_or_create_family


async def _make_active_menu(db_session, family_id: int, meals: list[dict]):
    menu = await repositories.create_draft_menu(
        db_session,
        family_id=family_id,
        start_date=date(2026, 5, 27),
        days_count=2,
        meals=meals,
    )
    await repositories.approve_menu(db_session, menu_id=menu.id)
    return menu


async def test_morning_digest_shows_today_and_tomorrow(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    await _make_active_menu(
        db_session,
        family.id,
        [
            {"date": date(2026, 5, 27), "slot": "lunch", "dish_name": "Том кха с курицей",
             "side_dishes": [], "protein_kind": "chicken"},
            {"date": date(2026, 5, 27), "slot": "dinner", "dish_name": "Лосось с овощами",
             "side_dishes": [], "protein_kind": "fish"},
            {"date": date(2026, 5, 28), "slot": "lunch", "dish_name": "Стейк рибай",
             "side_dishes": ["салат"], "protein_kind": "beef"},
            {"date": date(2026, 5, 28), "slot": "dinner", "dish_name": "Креветки в чесночном соусе",
             "side_dishes": [], "protein_kind": "seafood"},
        ],
    )

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 27)
    )

    assert text is not None
    assert "Сегодня" in text
    assert "среда, 27 мая" in text
    assert "Том кха с курицей" in text
    assert "Лосось с овощами" in text
    assert "Завтра" in text
    assert "четверг, 28 мая" in text
    assert "Стейк рибай" in text
    assert "Креветки в чесночном соусе" in text
    assert "разморозку" in text


async def test_morning_digest_only_today_when_no_tomorrow(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    await _make_active_menu(
        db_session,
        family.id,
        [
            {"date": date(2026, 5, 27), "slot": "lunch", "dish_name": "Курица",
             "side_dishes": [], "protein_kind": "chicken"},
            {"date": date(2026, 5, 27), "slot": "dinner", "dish_name": "Рыба",
             "side_dishes": [], "protein_kind": "fish"},
        ],
    )

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 27)
    )

    assert text is not None
    assert "Сегодня" in text
    assert "Курица" in text
    assert "Завтра" not in text


async def test_morning_digest_returns_none_when_no_active_menu(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 27)
    )

    assert text is None


async def test_morning_digest_returns_none_when_menu_in_the_past(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    await _make_active_menu(
        db_session,
        family.id,
        [
            {"date": date(2026, 5, 20), "slot": "lunch", "dish_name": "Старое",
             "side_dishes": [], "protein_kind": "chicken"},
        ],
    )

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 27)
    )

    assert text is None
