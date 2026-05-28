import json
from datetime import date

import pytest

from core import repositories
from core.services import menu_loader, shopping_list
from core.services.family_service import get_or_create_family


def _menu_json(start: str, meals: list[dict]) -> bytes:
    return json.dumps({"start_date": start, "meals": meals}).encode()


def _meal(d: str, slot: str, name: str, protein: str = "chicken") -> dict:
    return {
        "date": d,
        "slot": slot,
        "dish_name": name,
        "side_dishes": [],
        "protein_kind": protein,
    }


TODAY = date(2026, 5, 28)


async def test_first_load_with_no_existing_menu_has_no_conflicts(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    raw = _menu_json(
        "2026-05-28",
        [_meal("2026-05-28", "lunch", "A"), _meal("2026-05-28", "dinner", "B")],
    )

    preview = await menu_loader.preview_load(
        db_session, family_id=family.id, raw=raw, today=TODAY
    )

    assert preview.conflicting_dates == set()

    menu = await menu_loader.commit_load(
        db_session, family_id=family.id, parsed=preview.parsed, today=TODAY
    )
    assert menu.days_count == 1
    future = await repositories.get_future_meals(db_session, family.id, TODAY)
    assert [m.dish_name for m in future] == ["A", "B"]


async def test_loading_non_overlapping_future_dates_just_adds(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    first = await menu_loader.preview_load(
        db_session,
        family_id=family.id,
        raw=_menu_json("2026-05-28", [_meal("2026-05-28", "lunch", "Day1")]),
        today=TODAY,
    )
    await menu_loader.commit_load(
        db_session, family_id=family.id, parsed=first.parsed, today=TODAY
    )

    second_raw = _menu_json("2026-05-29", [_meal("2026-05-29", "lunch", "Day2")])
    second = await menu_loader.preview_load(
        db_session, family_id=family.id, raw=second_raw, today=TODAY
    )
    assert second.conflicting_dates == set()
    await menu_loader.commit_load(
        db_session, family_id=family.id, parsed=second.parsed, today=TODAY
    )

    future = await repositories.get_future_meals(db_session, family.id, TODAY)
    assert [(m.date.isoformat(), m.dish_name) for m in future] == [
        ("2026-05-28", "Day1"),
        ("2026-05-29", "Day2"),
    ]


async def test_loading_overlapping_future_date_returns_conflict(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    first = await menu_loader.preview_load(
        db_session,
        family_id=family.id,
        raw=_menu_json(
            "2026-05-28",
            [
                _meal("2026-05-28", "lunch", "Old1"),
                _meal("2026-05-29", "lunch", "Old2"),
            ],
        ),
        today=TODAY,
    )
    await menu_loader.commit_load(
        db_session, family_id=family.id, parsed=first.parsed, today=TODAY
    )

    second = await menu_loader.preview_load(
        db_session,
        family_id=family.id,
        raw=_menu_json(
            "2026-05-29",
            [
                _meal("2026-05-29", "lunch", "New2"),
                _meal("2026-05-30", "lunch", "New3"),
            ],
        ),
        today=TODAY,
    )
    assert second.conflicting_dates == {date(2026, 5, 29)}


async def test_commit_overwrites_only_conflicting_dates(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    first = await menu_loader.preview_load(
        db_session,
        family_id=family.id,
        raw=_menu_json(
            "2026-05-28",
            [
                _meal("2026-05-28", "lunch", "Old28"),
                _meal("2026-05-29", "lunch", "Old29"),
            ],
        ),
        today=TODAY,
    )
    await menu_loader.commit_load(
        db_session, family_id=family.id, parsed=first.parsed, today=TODAY
    )

    second = await menu_loader.preview_load(
        db_session,
        family_id=family.id,
        raw=_menu_json(
            "2026-05-29",
            [
                _meal("2026-05-29", "lunch", "New29"),
                _meal("2026-05-30", "lunch", "New30"),
            ],
        ),
        today=TODAY,
    )
    await menu_loader.commit_load(
        db_session, family_id=family.id, parsed=second.parsed, today=TODAY
    )

    future = await repositories.get_future_meals(db_session, family.id, TODAY)
    assert [(m.date.isoformat(), m.dish_name) for m in future] == [
        ("2026-05-28", "Old28"),
        ("2026-05-29", "New29"),
        ("2026-05-30", "New30"),
    ]


async def test_past_dates_never_count_as_conflicts(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    first = await menu_loader.preview_load(
        db_session,
        family_id=family.id,
        raw=_menu_json("2026-05-20", [_meal("2026-05-20", "lunch", "Past")]),
        today=TODAY,
    )
    await menu_loader.commit_load(
        db_session, family_id=family.id, parsed=first.parsed, today=TODAY
    )

    second = await menu_loader.preview_load(
        db_session,
        family_id=family.id,
        raw=_menu_json("2026-05-20", [_meal("2026-05-20", "lunch", "Past2")]),
        today=TODAY,
    )
    assert second.conflicting_dates == set()


async def test_load_does_not_touch_shopping_items(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    await shopping_list.add_manual_item(
        db_session, family_id=family.id, name="туалетная бумага"
    )

    raw = _menu_json("2026-05-28", [_meal("2026-05-28", "lunch", "X")])
    preview = await menu_loader.preview_load(
        db_session, family_id=family.id, raw=raw, today=TODAY
    )
    await menu_loader.commit_load(
        db_session, family_id=family.id, parsed=preview.parsed, today=TODAY
    )

    open_items = await repositories.get_open_shopping_items(
        db_session, family_id=family.id
    )
    assert [i.name for i in open_items] == ["туалетная бумага"]


async def test_invalid_json_raises(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    with pytest.raises(menu_loader.MenuLoadError):
        await menu_loader.preview_load(
            db_session, family_id=family.id, raw=b"not json", today=TODAY
        )


async def test_empty_meals_raises(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    with pytest.raises(menu_loader.MenuLoadError):
        await menu_loader.preview_load(
            db_session,
            family_id=family.id,
            raw=_menu_json("2026-05-28", []),
            today=TODAY,
        )


async def test_start_date_after_last_meal_raises(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    raw = _menu_json("2026-06-10", [_meal("2026-05-28", "lunch", "X")])
    with pytest.raises(menu_loader.MenuLoadError):
        await menu_loader.preview_load(
            db_session, family_id=family.id, raw=raw, today=TODAY
        )
