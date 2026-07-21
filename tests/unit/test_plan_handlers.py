"""Хендлер-тесты /plan на AsyncMock (без aiogram-харнесса)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import plan as plan_handler
from core.exceptions import LLMInvalidResponse


def _family(**kw):
    return SimpleNamespace(
        id=1, timezone="UTC", plan_slots=["lunch", "dinner"], profile_md="п", **kw
    )


async def test_generation_failure_shows_retry(monkeypatch):
    async def boom(*a, **kw):
        raise LLMInvalidResponse("bad json twice")

    monkeypatch.setattr(plan_handler.menu_planner, "generate_menu", boom)
    message, state = AsyncMock(), AsyncMock()
    state.get_data.return_value = {"start_date": "2026-07-27", "days": 5}
    member = SimpleNamespace(display_name="Юля", telegram_user_id=1, role="admin")

    await plan_handler._generate_and_show(message, state, _family(), member, db_session=None)

    placeholder = message.answer.return_value
    placeholder.edit_text.assert_awaited_once()
    assert "Не получилось" in placeholder.edit_text.await_args.args[0]


async def test_custom_date_rejects_garbage():
    message, state = AsyncMock(), AsyncMock()
    message.text = "вчера"
    await plan_handler.on_custom_date(message, state, _family())
    assert "Не понял дату" in message.answer.await_args.args[0]
    state.update_data.assert_not_awaited()


async def test_planning_disabled_filter_reads_flag(monkeypatch):
    monkeypatch.setattr(plan_handler, "_planning_enabled", lambda: False)
    assert await plan_handler._planning_disabled_filter(AsyncMock()) is True
    monkeypatch.setattr(plan_handler, "_planning_enabled", lambda: True)
    assert await plan_handler._planning_disabled_filter(AsyncMock()) is False


async def test_plan_stub_when_flag_off():
    message = AsyncMock()
    await plan_handler.cmd_plan_disabled(message)
    assert "скоро" in message.answer.await_args.args[0]


async def test_pick_alternative_out_of_range_alerts():
    cb, state = AsyncMock(), AsyncMock()
    cb.data = "plan:alt:5"
    state.get_data.return_value = {"alternatives": [], "replace_meal_id": 1}
    await plan_handler.on_pick_alternative(cb, state, _family(), db_session=None)
    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.kwargs.get("show_alert") is True
