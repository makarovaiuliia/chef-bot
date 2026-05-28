from datetime import date

from core.db import MealSlot, ProteinKind
from core.models import MealDTO


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
