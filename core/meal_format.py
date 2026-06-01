"""Canonical meal rendering: main dish plus side dishes joined with " + ".

Shared by the morning digest and the /today and /menu handlers so every
surface shows a meal the same way and never duplicates side dishes.
"""
from core.db import Meal, MealSlot

_SLOT_LABEL = {MealSlot.lunch: "Обед", MealSlot.dinner: "Ужин"}


def format_dish_with_sides(dish_name: str, side_dishes: list[str] | None) -> str:
    sides = [s.strip() for s in (side_dishes or []) if s and s.strip()]
    if not sides:
        return dish_name
    return " + ".join([dish_name, *sides])


def format_meal_lines(meals: list[Meal]) -> list[str]:
    """Bold "Обед:/Ужин:" lines for one day, lunch first, dinner second."""
    lines: list[str] = []
    for slot in (MealSlot.lunch, MealSlot.dinner):
        meal = next((m for m in meals if m.slot == slot), None)
        if meal is not None:
            dish = format_dish_with_sides(meal.dish_name, meal.side_dishes)
            lines.append(f"<b>{_SLOT_LABEL[slot]}:</b> {dish}")
    return lines
