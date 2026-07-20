from datetime import date

from core.db import (
    Family,
    LlmUsage,
    MealSlot,
    MemberRole,
    ProteinKind,
    ShoppingItem,
)
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


def test_member_role_values():
    assert MemberRole.admin == "admin"
    assert MemberRole.member == "member"


def test_meal_slot_has_breakfast():
    assert MealSlot.breakfast == "breakfast"


def test_family_defaults():
    # column defaults применяются на flush; проверяем определения колонок
    cols = Family.__table__.c
    assert cols.timezone.default.arg == "UTC"
    assert cols.digest_hour.default.arg == 9
    # SQLAlchemy оборачивает zero-arg lambda из модели в callable(ctx)
    assert cols.plan_slots.default.arg(None) == ["lunch", "dinner"]


def test_shopping_item_store_is_plain_string():
    item = ShoppingItem(family_id=1, name="молоко", store="пятёрочка")
    assert item.store == "пятёрочка"


def test_llm_usage_model_columns():
    u = LlmUsage(family_id=1, operation="profile", tokens_in=100, tokens_out=200)
    assert u.operation == "profile"
