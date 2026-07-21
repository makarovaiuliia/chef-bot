from datetime import date

from bot.keyboards import kb_meal_recipes
from core.db import Meal, MealSlot


def _meal(meal_id: int, slot: MealSlot, dish: str) -> Meal:
    m = Meal(date=date(2026, 7, 21), slot=slot, dish_name=dish, side_dishes=[])
    m.id = meal_id
    return m


def test_recipe_buttons_one_per_meal():
    kb = kb_meal_recipes([_meal(1, MealSlot.lunch, "Тефтели"), _meal(2, MealSlot.dinner, "Лосось")])
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert datas == ["meal:recipe:1", "meal:recipe:2"]
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert "Тефтели" in texts[0] and "Обед" in texts[0]
