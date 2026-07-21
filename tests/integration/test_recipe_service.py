from datetime import date
from unittest.mock import AsyncMock

from core import repositories
from core.llm import LLMResponse
from core.repositories import count_llm_operations
from core.services import recipe_service
from core.services.family_service import create_family


async def test_get_recipe_generates_and_caches(db_session, monkeypatch):
    family, _ = await create_family(
        db_session,
        telegram_user_id=111,
        display_name=None,
        profile_md="тестовый профиль",
        timezone="UTC",
        plan_slots=["lunch", "dinner"],
    )
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

    recipe1 = await recipe_service.get_recipe(
        db_session, meal_id=meal_id, profile_md="тестовый профиль", family_id=family.id
    )
    assert "Курица" in recipe1.content_md
    assert recipe1.prep_minutes == 30

    fake_client.chat.reset_mock()
    recipe2 = await recipe_service.get_recipe(
        db_session, meal_id=meal_id, profile_md="тестовый профиль", family_id=family.id
    )
    assert recipe2.id == recipe1.id
    fake_client.chat.assert_not_called()


async def test_recipe_generation_logs_usage(db_session, monkeypatch):
    family, _ = await create_family(
        db_session,
        telegram_user_id=222,
        display_name=None,
        profile_md="тестовый профиль",
        timezone="UTC",
        plan_slots=["lunch", "dinner"],
    )
    menu = await repositories.create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=date(2026, 5, 27),
        days_count=1,
        meals=[
            {
                "date": date(2026, 5, 27),
                "slot": "lunch",
                "dish_name": "Рыба в духовке",
                "side_dishes": ["рис"],
                "protein_kind": "fish",
            }
        ],
    )
    meal_id = menu.meals[0].id

    recipe_json = (
        '{"content_md": "# Рыба\\n\\n1. Замариновать\\n2. Запечь 25 минут",'
        ' "ingredients": [{"name": "рыба", "quantity": "500", "unit": "г"}],'
        ' "prep_minutes": 25}'
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(
        return_value=LLMResponse(
            text=recipe_json, stop_reason="end_turn", tokens_in=100, tokens_out=200
        )
    )
    monkeypatch.setattr(recipe_service, "get_llm_client", lambda: fake_client)

    # первый вызов - генерация
    await recipe_service.get_recipe(
        db_session, meal_id=meal_id, profile_md="п", family_id=family.id
    )
    assert await count_llm_operations(db_session, family_id=family.id, operation="recipe") == 1

    # второй - из кэша, счетчик не растет
    await recipe_service.get_recipe(
        db_session, meal_id=meal_id, profile_md="п", family_id=family.id
    )
    assert await count_llm_operations(db_session, family_id=family.id, operation="recipe") == 1
