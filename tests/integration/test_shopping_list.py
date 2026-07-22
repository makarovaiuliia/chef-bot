import json
from datetime import date
from unittest.mock import AsyncMock

import pytest

from bot.handlers.shopping import _notify_added
from config import get_settings
from core import repositories
from core.db import Family
from core.exceptions import LLMInvalidResponse, MonthlyCapExceeded
from core.llm import LLMResponse
from core.repositories import (
    count_llm_operations,
    create_draft_menu,
    get_open_shopping_items,
    log_llm_usage,
)
from core.services import shopping_list
from core.services.family_service import create_family, join_by_invite

_ITEMS = json.dumps({"items": [
    {"name": "Куриные бёдра", "quantity": "1 кг"},
    {"name": "Рис", "quantity": "500 г"},
]})

_ITEMS2 = json.dumps({"items": [
    {"name": "Морковь", "quantity": "3 шт"},
    {"name": "Гречка", "quantity": "400 г"},
]})


class FakeLLM:
    def __init__(self, texts):
        self._texts = list(texts)

    async def chat(self, **kwargs):
        return LLMResponse(text=self._texts.pop(0), tokens_in=50, tokens_out=60)


async def _family_with_menu(db_session):
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    d = date(2026, 7, 27)
    menu = await create_draft_menu(
        db_session, family_id=fam.id, start_date=d, days_count=1,
        meals=[{"date": d, "slot": "dinner", "dish_name": "Курица с рисом",
                "side_dishes": ["салат"], "protein_kind": "chicken"}],
    )
    return fam, menu


async def test_add_manual_item_creates_standalone_item(db_session):
    family, _ = await create_family(
        db_session,
        telegram_user_id=111,
        display_name=None,
        profile_md="тестовый профиль",
        timezone="UTC",
        plan_slots=["lunch", "dinner"],
    )

    item = await shopping_list.add_manual_item(
        db_session, family_id=family.id, name="молоко"
    )

    assert item.shopping_list_id is None
    assert item.name == "молоко"
    assert item.quantity == ""
    assert item.store is None
    assert item.bought is False

    items = await repositories.get_open_shopping_items(db_session, family_id=family.id)
    assert len(items) == 1
    assert items[0].name == "молоко"


async def test_toggle_bought_round_trip(db_session):
    family, _ = await create_family(
        db_session,
        telegram_user_id=111,
        display_name=None,
        profile_md="тестовый профиль",
        timezone="UTC",
        plan_slots=["lunch", "dinner"],
    )

    item = await shopping_list.add_manual_item(
        db_session, family_id=family.id, name="молоко"
    )

    toggled = await shopping_list.toggle_bought(
        db_session, item_id=item.id, family_id=family.id
    )
    assert toggled.bought is True

    items_after = await repositories.get_open_shopping_items(db_session, family_id=family.id)
    assert items_after == []


async def test_toggle_bought_cannot_touch_other_family_item(db_session):
    """Regression: item_id из чужой семьи не должен переключаться (IDOR)."""
    family_a, _ = await create_family(
        db_session,
        telegram_user_id=111,
        display_name=None,
        profile_md="профиль A",
        timezone="UTC",
        plan_slots=["dinner"],
    )
    family_b, _ = await create_family(
        db_session,
        telegram_user_id=222,
        display_name=None,
        profile_md="профиль B",
        timezone="UTC",
        plan_slots=["dinner"],
    )

    item = await shopping_list.add_manual_item(
        db_session, family_id=family_a.id, name="молоко"
    )

    result = await shopping_list.toggle_bought(
        db_session, item_id=item.id, family_id=family_b.id
    )

    assert result is None
    assert item.bought is False
    items_a = await repositories.get_open_shopping_items(
        db_session, family_id=family_a.id
    )
    assert [i.id for i in items_a] == [item.id]


async def test_notify_added_swallows_send_failure(db_session):
    """Заблокировавший бота член семьи не должен ронять хендлер (и транзакцию)."""
    family, adder = await create_family(
        db_session,
        telegram_user_id=111,
        display_name="Юля",
        profile_md="p",
        timezone="UTC",
        plan_slots=["dinner"],
    )
    await join_by_invite(
        db_session, invite_code=family.invite_code,
        telegram_user_id=222, display_name="Вова",
    )
    message = AsyncMock()
    message.bot.send_message.side_effect = Exception("bot was blocked by the user")

    await _notify_added(message, family, adder, db_session, ["молоко"])

    message.bot.send_message.assert_awaited_once()


async def test_build_from_menu_creates_items_and_logs(db_session):
    fam, menu = await _family_with_menu(db_session)
    items = await shopping_list.build_from_menu(
        db_session, family_id=fam.id, menu=menu, profile_md="п", llm=FakeLLM([_ITEMS])
    )
    assert [i.name for i in items] == ["Куриные бёдра", "Рис"]
    assert all(i.shopping_list_id is not None for i in items)
    assert await count_llm_operations(db_session, family_id=fam.id, operation="shopping") == 1


async def test_build_from_menu_closes_stale_keeps_manual(db_session):
    fam, menu = await _family_with_menu(db_session)
    await shopping_list.add_manual_item(db_session, family_id=fam.id, name="Молоко")
    first_items = await shopping_list.build_from_menu(
        db_session, family_id=fam.id, menu=menu, profile_md="п", llm=FakeLLM([_ITEMS])
    )
    # второе меню (другой набор блюд от LLM): пункты первого закрываются, ручной остаётся
    _, menu2 = await _family_with_menu(db_session)
    await shopping_list.build_from_menu(
        db_session, family_id=fam.id, menu=menu2, profile_md="п", llm=FakeLLM([_ITEMS2])
    )
    open_items = await get_open_shopping_items(db_session, family_id=fam.id)
    assert len(open_items) == 3  # молоко + 2 из второго билда
    assert {i.name for i in open_items} == {"Молоко", "Морковь", "Гречка"}
    assert all(i.bought is True for i in first_items)


async def test_build_from_menu_blocked_by_cap(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "monthly_token_cap_per_family", 10)
    fam, menu = await _family_with_menu(db_session)
    await shopping_list.add_manual_item(db_session, family_id=fam.id, name="Молоко")
    before = await get_open_shopping_items(db_session, family_id=fam.id)
    await log_llm_usage(
        db_session, family_id=fam.id, operation="recipe", tokens_in=10, tokens_out=10
    )
    llm = FakeLLM([_ITEMS])

    with pytest.raises(MonthlyCapExceeded):
        await shopping_list.build_from_menu(
            db_session, family_id=fam.id, menu=menu, profile_md="п", llm=llm
        )

    assert llm._texts == [_ITEMS]  # LLM не вызван — очередь текстов не тронута
    after = await get_open_shopping_items(db_session, family_id=fam.id)
    assert [i.id for i in after] == [i.id for i in before]


async def test_has_list_for_menu_false_then_true_after_build(db_session):
    fam, menu = await _family_with_menu(db_session)

    assert await shopping_list.has_list_for_menu(db_session, menu_id=menu.id) is False

    await shopping_list.build_from_menu(
        db_session, family_id=fam.id, menu=menu, profile_md="п", llm=FakeLLM([_ITEMS])
    )

    assert await shopping_list.has_list_for_menu(db_session, menu_id=menu.id) is True


async def test_build_from_menu_invalid_json_leaves_list_untouched(db_session):
    fam, menu = await _family_with_menu(db_session)
    await shopping_list.build_from_menu(
        db_session, family_id=fam.id, menu=menu, profile_md="п", llm=FakeLLM([_ITEMS])
    )
    before = await get_open_shopping_items(db_session, family_id=fam.id)
    before_count = await count_llm_operations(
        db_session, family_id=fam.id, operation="shopping"
    )

    with pytest.raises(LLMInvalidResponse):
        await shopping_list.build_from_menu(
            db_session, family_id=fam.id, menu=menu, profile_md="п", llm=FakeLLM(["мусор"])
        )

    after = await get_open_shopping_items(db_session, family_id=fam.id)
    assert [i.id for i in after] == [i.id for i in before]
    assert all(i.bought is False for i in after)
    assert (
        await count_llm_operations(db_session, family_id=fam.id, operation="shopping")
        == before_count
    )
