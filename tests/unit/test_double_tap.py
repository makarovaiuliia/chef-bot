"""Двойной тап по кнопкам генерации не должен запускать вторую LLM-операцию."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import inflight
from bot.handlers import menu as menu_handler
from bot.handlers import plan as plan_handler
from bot.inflight import BUSY_ALERT


@pytest.fixture(autouse=True)
def _clean():
    inflight.reset()
    yield
    inflight.reset()


FAMILY = SimpleNamespace(id=1, profile_md="", sub_until=None, timezone="UTC")
MEMBER = SimpleNamespace(id=1, telegram_user_id=111, display_name="Юля")


def _cb(data: str):
    cb = AsyncMock()
    cb.data = data
    return cb


async def test_second_tap_on_menu_generation_is_rejected(monkeypatch):
    generations = []

    async def slow_generate(message, state, family, family_member, db_session):
        generations.append(1)
        await asyncio.sleep(0.02)

    monkeypatch.setattr(plan_handler, "_generate_and_show", slow_generate)

    first, second = _cb("plan:days:3"), _cb("plan:days:3")
    state = AsyncMock()

    await asyncio.gather(
        plan_handler.on_duration(first, state, FAMILY, MEMBER, None),
        plan_handler.on_duration(second, state, FAMILY, MEMBER, None),
    )

    assert len(generations) == 1  # вторая генерация не стартовала
    alerts = [
        c for cb in (first, second)
        for c in cb.answer.await_args_list
        if c.args and c.args[0] == BUSY_ALERT
    ]
    assert len(alerts) == 1
    assert alerts[0].kwargs.get("show_alert") is True


async def test_second_tap_on_regenerate_is_rejected(monkeypatch):
    generations = []

    async def slow_generate(message, state, family, family_member, db_session):
        generations.append(1)
        await asyncio.sleep(0.02)

    async def noop_delete(session, *, menu_id):
        return None

    monkeypatch.setattr(plan_handler, "_generate_and_show", slow_generate)
    monkeypatch.setattr(plan_handler.menu_planner, "delete_draft", noop_delete)

    state = AsyncMock()
    state.get_data.return_value = {"menu_id": 5}

    await asyncio.gather(
        plan_handler.on_regenerate(_cb("plan:regen"), state, FAMILY, MEMBER, None),
        plan_handler.on_regenerate(_cb("plan:regen"), state, FAMILY, MEMBER, None),
    )

    assert len(generations) == 1


async def test_generation_slot_frees_up_after_failure(monkeypatch):
    """Упавшая генерация не должна навсегда запирать семью."""

    async def boom(message, state, family, family_member, db_session):
        raise RuntimeError("LLM упал")

    monkeypatch.setattr(plan_handler, "_generate_and_show", boom)

    with pytest.raises(RuntimeError):
        await plan_handler.on_duration(_cb("plan:days:3"), AsyncMock(), FAMILY, MEMBER, None)

    assert not inflight.is_busy(FAMILY.id)


async def test_cached_recipe_does_not_take_the_slot(monkeypatch):
    """Готовый рецепт отдается мгновенно и не мешает другой операции семьи."""
    monkeypatch.setattr(
        menu_handler.repositories,
        "get_meal_for_family",
        AsyncMock(return_value=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(
        menu_handler.repositories,
        "get_recipe",
        AsyncMock(return_value=SimpleNamespace(content_md="<b>Рецепт</b>")),
    )

    cb = _cb("meal:recipe:1")
    await menu_handler.cb_recipe(cb, FAMILY, db_session=None)

    assert not inflight.is_busy(FAMILY.id)
    placeholder = cb.message.answer.return_value
    assert "Рецепт" in placeholder.edit_text.await_args.args[0]


async def test_second_tap_on_recipe_is_rejected(monkeypatch):
    calls = []

    async def slow_recipe(message, meal, family, db_session):
        calls.append(1)
        await asyncio.sleep(0.02)

    monkeypatch.setattr(
        menu_handler.repositories,
        "get_meal_for_family",
        AsyncMock(return_value=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(
        menu_handler.repositories, "get_recipe", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(menu_handler, "_generate_recipe", slow_recipe)

    await asyncio.gather(
        menu_handler.cb_recipe(_cb("meal:recipe:1"), FAMILY, None),
        menu_handler.cb_recipe(_cb("meal:recipe:1"), FAMILY, None),
    )

    assert len(calls) == 1


async def test_replace_and_menu_generation_share_one_slot(monkeypatch):
    """Замена блюда и генерация меню — обе LLM-операции семьи, слот один."""
    suggestions = []

    async def slow_suggest(message, state, family, db_session, *, hint):
        suggestions.append(1)
        await asyncio.sleep(0.02)

    async def slow_generate(message, state, family, family_member, db_session):
        await asyncio.sleep(0.02)

    monkeypatch.setattr(plan_handler, "_suggest_and_show", slow_suggest)
    monkeypatch.setattr(plan_handler, "_generate_and_show", slow_generate)

    state = AsyncMock()
    pick = _cb("plan:rm:9")

    await asyncio.gather(
        plan_handler.on_duration(_cb("plan:days:3"), state, FAMILY, MEMBER, None),
        plan_handler.on_pick_meal(pick, state, FAMILY, None),
    )

    # Одна из двух операций отбита алертом.
    assert len(suggestions) == 0
    assert any(
        c.args and c.args[0] == BUSY_ALERT for c in pick.answer.await_args_list
    )
