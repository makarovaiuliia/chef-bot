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
