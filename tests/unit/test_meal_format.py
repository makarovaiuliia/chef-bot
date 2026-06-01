from core.db import Meal, MealSlot
from core.meal_format import format_dish_with_sides, format_meal_lines


def _meal(slot: MealSlot, dish: str, sides: list[str]) -> Meal:
    return Meal(slot=slot, dish_name=dish, side_dishes=sides)


def test_format_meal_lines_lunch_and_dinner():
    meals = [
        _meal(MealSlot.dinner, "Свинина-вырезка", ["картофель"]),
        _meal(MealSlot.lunch, "Говяжьи тефтели", ["булгур", "овощная смесь"]),
    ]
    assert format_meal_lines(meals) == [
        "<b>Обед:</b> Говяжьи тефтели + булгур + овощная смесь",
        "<b>Ужин:</b> Свинина-вырезка + картофель",
    ]


def test_format_meal_lines_only_lunch():
    meals = [_meal(MealSlot.lunch, "Курица", [])]
    assert format_meal_lines(meals) == ["<b>Обед:</b> Курица"]


def test_dish_with_multiple_sides():
    assert (
        format_dish_with_sides("Говяжьи тефтели", ["булгур", "овощная смесь"])
        == "Говяжьи тефтели + булгур + овощная смесь"
    )


def test_dish_with_single_side():
    assert format_dish_with_sides("Курица", ["рис"]) == "Курица + рис"


def test_dish_without_sides():
    assert format_dish_with_sides("Курица", []) == "Курица"


def test_dish_with_none_sides():
    assert format_dish_with_sides("Курица", None) == "Курица"


def test_strips_empty_side_entries():
    assert format_dish_with_sides("Курица", ["рис", "", "  "]) == "Курица + рис"
