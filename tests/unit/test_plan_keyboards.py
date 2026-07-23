from datetime import date

from bot.keyboards import (
    kb_plan_alternatives,
    kb_plan_approve_confirm,
    kb_plan_draft,
    kb_plan_duration,
    kb_plan_meals,
    kb_plan_reminder,
    kb_plan_start,
    kb_retry,
    kb_shoplist_offer,
)
from core.db import Meal, MealSlot


def _datas(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def test_plan_start_buttons():
    datas = _datas(kb_plan_start())
    assert datas == [
        "plan:date:today",
        "plan:date:tomorrow",
        "plan:date:monday",
        "plan:date:custom",
    ]


def test_plan_duration_buttons():
    assert _datas(kb_plan_duration()) == ["plan:days:3", "plan:days:5", "plan:days:7"]


def test_plan_draft_actions():
    datas = _datas(kb_plan_draft())
    assert datas == ["plan:replace", "plan:regen", "plan:approve"]


def test_retry_keyboard():
    assert _datas(kb_retry("plan:regen")) == ["plan:regen"]


def test_plan_meals_button_per_meal_plus_back():
    m = Meal(date=date(2026, 7, 27), slot=MealSlot.lunch, dish_name="Тефтели", side_dishes=[])
    m.id = 42
    datas = _datas(kb_plan_meals([m]))
    assert datas == ["plan:rm:42", "plan:back"]


def test_plan_alternatives_numbered_plus_hint_and_back():
    datas = _datas(kb_plan_alternatives(3))
    assert datas == ["plan:alt:0", "plan:alt:1", "plan:alt:2", "plan:althint", "plan:back"]


def test_plan_approve_confirm_buttons():
    datas = _datas(kb_plan_approve_confirm())
    assert datas == ["plan:approveyes", "plan:approveno"]


def test_shoplist_offer_two_buttons():
    assert _datas(kb_shoplist_offer(7)) == ["plan:shoplist:7", "plan:shoptext:7"]


def test_plan_reminder_button():
    assert _datas(kb_plan_reminder()) == ["plan:remind"]
