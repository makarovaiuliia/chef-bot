from datetime import date
from unittest.mock import AsyncMock

from core import repositories
from core.llm import LLMResponse
from core.services import shopping_list
from core.services.family_service import get_or_create_family


async def test_build_from_menu_creates_grouped_items(db_session, monkeypatch):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    menu = await repositories.create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=date(2026, 5, 26),
        days_count=1,
        meals=[
            {
                "date": date(2026, 5, 26),
                "slot": "lunch",
                "dish_name": "Курица",
                "side_dishes": ["рис"],
                "protein_kind": "chicken",
            },
            {
                "date": date(2026, 5, 26),
                "slot": "dinner",
                "dish_name": "Лосось с фетой",
                "side_dishes": ["салат"],
                "protein_kind": "fish",
            },
        ],
    )

    llm_json = (
        '{"items": ['
        '{"name": "Куриные бёдра", "quantity": "500 г", "store": "makro"},'
        '{"name": "Лосось", "quantity": "300 г", "store": "makro"},'
        '{"name": "Фета", "quantity": "200 г", "store": "villa"}'
        "]}"
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(
        return_value=LLMResponse(text=llm_json, stop_reason="end_turn")
    )
    monkeypatch.setattr(shopping_list, "get_llm_client", lambda: fake_client)

    await shopping_list.build_from_menu(db_session, menu_id=menu.id, family_id=family.id)
    items = await repositories.get_open_shopping_items(db_session, family_id=family.id)
    assert len(items) == 3
    assert any(i.name == "Фета" and i.store.value == "villa" for i in items)


async def test_approve_new_menu_closes_old_menu_items_keeps_manual(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)

    # Old menu with shopping list
    old_menu = await repositories.create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=date(2026, 5, 20),
        days_count=1,
        meals=[
            {
                "date": date(2026, 5, 20),
                "slot": "lunch",
                "dish_name": "Курица",
                "side_dishes": [],
                "protein_kind": "chicken",
            }
        ],
    )
    await repositories.create_shopping_list(
        db_session,
        menu_id=old_menu.id,
        family_id=family.id,
        items=[
            {"name": "курица", "quantity": "500г", "store": "makro"},
            {"name": "рис", "quantity": "1кг", "store": "makro"},
        ],
    )
    await repositories.approve_menu(db_session, menu_id=old_menu.id)

    # User adds a manual item
    await shopping_list.add_manual_item(
        db_session, family_id=family.id, name="туалетная бумага"
    )

    # Confirm initial state: 3 open items
    assert len(await repositories.get_open_shopping_items(db_session, family_id=family.id)) == 3

    # New menu approved → old menu's items closed, manual item stays
    new_menu = await repositories.create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=date(2026, 5, 27),
        days_count=1,
        meals=[
            {
                "date": date(2026, 5, 27),
                "slot": "lunch",
                "dish_name": "Рыба",
                "side_dishes": [],
                "protein_kind": "fish",
            }
        ],
    )
    await repositories.approve_menu(db_session, menu_id=new_menu.id)

    open_items = await repositories.get_open_shopping_items(db_session, family_id=family.id)
    assert len(open_items) == 1
    assert open_items[0].name == "туалетная бумага"
    assert open_items[0].shopping_list_id is None


async def test_add_manual_item_creates_standalone_item(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)

    item = await shopping_list.add_manual_item(
        db_session, family_id=family.id, name="молоко"
    )

    assert item.shopping_list_id is None
    assert item.name == "молоко"
    assert item.quantity == ""
    assert item.store.value == "other"
    assert item.bought is False

    items = await repositories.get_open_shopping_items(db_session, family_id=family.id)
    assert len(items) == 1
    assert items[0].name == "молоко"


async def test_toggle_bought_round_trip(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    menu = await repositories.create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=date(2026, 5, 26),
        days_count=1,
        meals=[
            {
                "date": date(2026, 5, 26),
                "slot": "lunch",
                "dish_name": "Курица",
                "side_dishes": [],
                "protein_kind": "chicken",
            }
        ],
    )
    await repositories.create_shopping_list(
        db_session,
        menu_id=menu.id,
        family_id=family.id,
        items=[{"name": "молоко", "quantity": "1 л", "store": "makro"}],
    )
    items = await repositories.get_open_shopping_items(db_session, family_id=family.id)
    assert len(items) == 1
    item_id = items[0].id

    toggled = await shopping_list.toggle_bought(db_session, item_id=item_id)
    assert toggled.bought is True

    items_after = await repositories.get_open_shopping_items(db_session, family_id=family.id)
    assert items_after == []
