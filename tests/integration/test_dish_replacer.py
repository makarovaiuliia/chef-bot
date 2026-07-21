import json
from datetime import date
from unittest.mock import AsyncMock

import pytest

from core import repositories
from core.db import ProteinKind
from core.exceptions import LLMInvalidResponse
from core.llm import LLMResponse
from core.services import dish_replacer
from core.services.dish_replacer import ReplacementOption, apply_replacement, suggest_replacements
from core.services.family_service import create_family

_ALTERNATIVES = json.dumps(
    {
        "alternatives": [
            {"dish_name": "Лосось на пару", "side_dishes": ["рис"], "protein_kind": "fish"},
            {"dish_name": "Креветки вок", "side_dishes": ["лапша"], "protein_kind": "seafood"},
        ]
    }
)


async def _make_family_and_meal(db_session):
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
                "dish_name": "Курица",
                "side_dishes": ["рис"],
                "protein_kind": "chicken",
            }
        ],
    )
    return family, menu.meals[0]


def _mock_llm(monkeypatch, text: str):
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(return_value=LLMResponse(text=text, stop_reason="end_turn"))
    monkeypatch.setattr(dish_replacer, "get_llm_client", lambda: fake_client)
    return fake_client


async def test_suggest_returns_options_and_logs_usage(db_session, monkeypatch):
    family, meal = await _make_family_and_meal(db_session)
    _mock_llm(monkeypatch, _ALTERNATIVES)

    options = await suggest_replacements(
        db_session, meal_id=meal.id, hint="с рыбой", profile_md="п", family_id=family.id
    )

    assert [o.dish_name for o in options] == ["Лосось на пару", "Креветки вок"]
    fresh = await repositories.get_meal(db_session, meal.id)
    assert fresh.dish_name != "Лосось на пару"
    assert await repositories.count_llm_operations(
        db_session, family_id=family.id, operation="replace"
    ) == 1


async def test_apply_replacement_updates_meal_and_drops_recipe(db_session, monkeypatch):
    _, meal = await _make_family_and_meal(db_session)
    option = ReplacementOption(dish_name="Лосось", side_dishes=["рис"], protein_kind="fish")

    meal2 = await apply_replacement(db_session, meal_id=meal.id, option=option)

    assert meal2.dish_name == "Лосось"
    assert meal2.protein_kind == ProteinKind.fish


async def test_suggest_invalid_json_raises_and_logs_nothing(db_session, monkeypatch):
    family, meal = await _make_family_and_meal(db_session)
    _mock_llm(monkeypatch, "мусор")

    with pytest.raises(LLMInvalidResponse):
        await suggest_replacements(
            db_session, meal_id=meal.id, hint=None, profile_md="п", family_id=family.id
        )

    assert await repositories.count_llm_operations(
        db_session, family_id=family.id, operation="replace"
    ) == 0


async def test_replace_meal_swaps_dish(db_session, monkeypatch):
    family, meal = await _make_family_and_meal(db_session)
    _mock_llm(monkeypatch, _ALTERNATIVES)

    result = await dish_replacer.replace_meal(
        db_session, meal_id=meal.id, hint="с рыбой", profile_md="тестовый профиль",
        family_id=family.id,
    )

    assert result.dish_name == "Лосось на пару"
    assert result.protein_kind == ProteinKind.fish
    assert await repositories.count_llm_operations(
        db_session, family_id=family.id, operation="replace"
    ) == 1
