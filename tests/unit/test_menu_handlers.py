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


async def test_cmd_menu_empty_no_json_mention(monkeypatch):
    async def no_meals(*a, **kw):
        return []

    monkeypatch.setattr(menu_handler.repositories, "get_future_meals", no_meals)
    message = AsyncMock()
    await menu_handler.cmd_menu(message, SimpleNamespace(id=1), db_session=None)
    text = message.answer.await_args.args[0]
    assert "JSON" not in text and "/plan" in text


async def test_cmd_today_empty_no_json_mention(monkeypatch):
    async def no_meals(*a, **kw):
        return []

    monkeypatch.setattr(menu_handler.repositories, "get_meals_for_date", no_meals)
    message = AsyncMock()
    await menu_handler.cmd_today(message, SimpleNamespace(id=1), db_session=None)
    text = message.answer.await_args.args[0]
    assert "JSON" not in text and "/plan" in text


async def test_cb_recipe_trial_denial_shows_polite_text_with_button(monkeypatch):
    from core.exceptions import TrialLimitExceeded

    async def blocked(*a, **kw):
        raise TrialLimitExceeded("recipe")

    monkeypatch.setattr(
        menu_handler.repositories,
        "get_meal_for_family",
        AsyncMock(return_value=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(menu_handler.recipe_service, "get_recipe", blocked)
    cb = AsyncMock()
    cb.data = "meal:recipe:1"

    await menu_handler.cb_recipe(
        cb, SimpleNamespace(id=1, profile_md="", sub_until=None), db_session=None
    )

    placeholder = cb.message.answer.return_value
    text = placeholder.edit_text.await_args.args[0]
    assert "лимит" in text.lower() and "подписка" in text.lower()
    assert placeholder.edit_text.await_args.kwargs.get("reply_markup") is not None
