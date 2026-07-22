"""Рецепты доступны только из /today (решение 2026-07-21): /menu — без кнопок."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import menu as menu_handler
from core.db import MealSlot


def _meal(d: date, slot: MealSlot) -> SimpleNamespace:
    return SimpleNamespace(id=1, date=d, slot=slot, dish_name="Блюдо", side_dishes=[])


async def test_cmd_menu_has_no_recipe_buttons(monkeypatch):
    async def fake_meals(*a, **kw):
        return [_meal(date(2026, 7, 27), MealSlot.lunch)]

    monkeypatch.setattr(menu_handler.repositories, "get_future_meals", fake_meals)
    message = AsyncMock()

    await menu_handler.cmd_menu(message, SimpleNamespace(id=1), db_session=None)

    assert message.answer.await_args.kwargs.get("reply_markup") is None


async def test_cmd_today_keeps_recipe_buttons(monkeypatch):
    async def fake_meals(*a, **kw):
        return [_meal(date(2026, 7, 27), MealSlot.lunch)]

    monkeypatch.setattr(menu_handler.repositories, "get_meals_for_date", fake_meals)
    message = AsyncMock()

    await menu_handler.cmd_today(message, SimpleNamespace(id=1), db_session=None)

    assert message.answer.await_args.kwargs.get("reply_markup") is not None
