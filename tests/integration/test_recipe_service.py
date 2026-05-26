from datetime import date
from unittest.mock import AsyncMock

from core import repositories
from core.llm import LLMResponse
from core.services import recipe_service
from core.services.family_service import get_or_create_family


async def test_get_recipe_generates_and_caches(db_session, monkeypatch):
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
                "dish_name": "Курица в airfryer",
                "side_dishes": ["гречка"],
                "protein_kind": "chicken",
            }
        ],
    )
    meal_id = menu.meals[0].id

    recipe_json = (
        '{"content_md": "# Курица\\n\\n1. Замариновать\\n2. Жарить 25 минут",'
        ' "ingredients": [{"name": "куриные бёдра", "quantity": "500", "unit": "г",'
        ' "store": "Makro"}], "prep_minutes": 30}'
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(
        return_value=LLMResponse(text=recipe_json, stop_reason="end_turn")
    )
    monkeypatch.setattr(recipe_service, "get_llm_client", lambda: fake_client)

    recipe1 = await recipe_service.get_recipe(db_session, meal_id=meal_id)
    assert "Курица" in recipe1.content_md
    assert recipe1.prep_minutes == 30

    fake_client.chat.reset_mock()
    recipe2 = await recipe_service.get_recipe(db_session, meal_id=meal_id)
    assert recipe2.id == recipe1.id
    fake_client.chat.assert_not_called()
