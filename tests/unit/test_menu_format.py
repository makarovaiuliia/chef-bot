from datetime import date

from bot.handlers.menu import _format_future_meals, _format_today
from core.db import Meal, MealSlot


def _meal(d: date, slot: MealSlot, dish: str, sides: list[str]) -> Meal:
    return Meal(date=d, slot=slot, dish_name=dish, side_dishes=sides)


def test_today_uses_sun_header_and_bold_labels():
    meals = [
        _meal(date(2026, 6, 1), MealSlot.lunch, "Говяжьи тефтели", ["булгур", "овощная смесь"]),
        _meal(date(2026, 6, 1), MealSlot.dinner, "Свинина-вырезка", ["картофель"]),
    ]
    text = _format_today(meals, date(2026, 6, 1))
    assert text == (
        "☀️ Сегодня · пн, 1 июня\n"
        "<b>Обед:</b> Говяжьи тефтели + булгур + овощная смесь\n"
        "<b>Ужин:</b> Свинина-вырезка + картофель"
    )


def test_future_menu_groups_days_with_calendar_headers():
    meals = [
        _meal(date(2026, 6, 1), MealSlot.lunch, "Тефтели", ["булгур"]),
        _meal(date(2026, 6, 1), MealSlot.dinner, "Вырезка", []),
        _meal(date(2026, 6, 2), MealSlot.lunch, "Рыба", ["киноа"]),
        _meal(date(2026, 6, 2), MealSlot.dinner, "Бёдра", []),
    ]
    text = _format_future_meals(meals, date(2026, 6, 1))
    assert text.startswith("<b>📋 Меню · 2 дн. с 01.06.2026</b>")
    assert "📅 пн, 1 июня" in text
    assert "📅 вт, 2 июня" in text
    assert "<b>Обед:</b> Тефтели + булгур" in text
    assert "<b>Ужин:</b> Бёдра" in text
    # no English weekday leakage from strftime("%a")
    assert "Mon" not in text and "Tue" not in text
