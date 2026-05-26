from datetime import date
from unittest.mock import AsyncMock

from core import repositories
from core.db import ProteinKind
from core.llm import LLMResponse
from core.services import dish_replacer
from core.services.family_service import get_or_create_family


async def test_replace_meal_swaps_dish(db_session, monkeypatch):
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
            }
        ],
    )
    meal_id = menu.meals[0].id

    new_dish_json = (
        '{"dish_name": "Жареный лосось", '
        '"side_dishes": ["брокколи на пару"], '
        '"protein_kind": "fish"}'
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(
        return_value=LLMResponse(text=new_dish_json, stop_reason="end_turn")
    )
    monkeypatch.setattr(dish_replacer, "get_llm_client", lambda: fake_client)

    meal = await dish_replacer.replace_meal(db_session, meal_id=meal_id, hint="с рыбой")
    assert meal.dish_name == "Жареный лосось"
    assert meal.protein_kind == ProteinKind.fish
