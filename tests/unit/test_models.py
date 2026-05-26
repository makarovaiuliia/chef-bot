from datetime import date

from core.db import MealSlot, ProteinKind
from core.models import LLMMenuResponse, MealDTO


def test_meal_dto_parsing():
    raw = {
        "date": "2026-05-26",
        "slot": "lunch",
        "dish_name": "Курица в airfryer с гречкой",
        "side_dishes": ["гречка", "брокколи"],
        "protein_kind": "chicken",
    }
    m = MealDTO.model_validate(raw)
    assert m.date == date(2026, 5, 26)
    assert m.slot == MealSlot.lunch
    assert m.protein_kind == ProteinKind.chicken


def test_llm_menu_response_parsing():
    raw = {
        "meals": [
            {
                "date": "2026-05-26",
                "slot": "lunch",
                "dish_name": "x",
                "side_dishes": [],
                "protein_kind": "fish",
            },
            {
                "date": "2026-05-26",
                "slot": "dinner",
                "dish_name": "y",
                "side_dishes": ["z"],
                "protein_kind": "beef",
            },
        ]
    }
    r = LLMMenuResponse.model_validate(raw)
    assert len(r.meals) == 2
