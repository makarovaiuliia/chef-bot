from datetime import date, timedelta

from core import repositories
from core.services import digest, shopping_list
from core.services.family_service import get_or_create_family


async def test_digest_includes_open_shopping_items(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    await _make_active_menu(
        db_session,
        family.id,
        [
            {"date": date(2026, 5, 27), "slot": "lunch", "dish_name": "Курица",
             "side_dishes": [], "protein_kind": "chicken"},
        ],
    )
    await shopping_list.add_manual_item(db_session, family_id=family.id, name="молоко")

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 27)
    )

    assert text is not None
    assert "Курица" in text
    assert "В списке покупок" in text


async def test_digest_fires_with_only_shopping_items_no_menu(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    await shopping_list.add_manual_item(db_session, family_id=family.id, name="молоко")

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 27)
    )

    assert text is not None
    assert "В списке покупок" in text
    assert "разморозку" not in text


async def test_digest_omits_shopping_line_when_list_empty(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    await _make_active_menu(
        db_session,
        family.id,
        [
            {"date": date(2026, 5, 27), "slot": "lunch", "dish_name": "Курица",
             "side_dishes": [], "protein_kind": "chicken"},
        ],
    )

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 27)
    )

    assert text is not None
    assert "В списке покупок" not in text


async def _make_active_menu(
    db_session,
    family_id: int,
    meals: list[dict],
    *,
    start_date: date = date(2026, 5, 27),
    days_count: int = 2,
):
    menu = await repositories.create_draft_menu(
        db_session,
        family_id=family_id,
        start_date=start_date,
        days_count=days_count,
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


async def _make_three_day_menu(db_session, family_id: int):
    meals = []
    for i, d in enumerate(
        [date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29)]
    ):
        meals.append(
            {"date": d, "slot": "lunch", "dish_name": f"Обед {i}",
             "side_dishes": [], "protein_kind": "chicken"}
        )
    await _make_active_menu(
        db_session,
        family_id,
        meals,
        start_date=date(2026, 5, 27),
        days_count=3,
    )


async def test_digest_warns_two_days_before_menu_ends(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    await _make_three_day_menu(db_session, family.id)

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 27)
    )

    assert text is not None
    assert "через 2 дня" in text


async def test_digest_warns_one_day_before_menu_ends(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    await _make_three_day_menu(db_session, family.id)

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 28)
    )

    assert text is not None
    assert "заканчивается завтра" in text


async def test_digest_does_not_warn_on_last_day(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    await _make_three_day_menu(db_session, family.id)

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 29)
    )

    assert text is not None
    assert "заканчивается" not in text


async def test_digest_does_not_warn_when_menu_has_many_days_left(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    meals = [
        {"date": date(2026, 5, 27) + timedelta(days=i), "slot": "lunch",
         "dish_name": f"Обед {i}", "side_dishes": [], "protein_kind": "chicken"}
        for i in range(7)
    ]
    await _make_active_menu(
        db_session,
        family.id,
        meals,
        start_date=date(2026, 5, 27),
        days_count=7,
    )

    text = await digest.build_morning_digest(
        db_session, family_id=family.id, today=date(2026, 5, 27)
    )

    assert text is not None
    assert "заканчивается" not in text
