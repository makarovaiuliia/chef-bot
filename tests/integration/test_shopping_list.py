from unittest.mock import AsyncMock

from bot.handlers.shopping import _notify_added
from core import repositories
from core.services import shopping_list
from core.services.family_service import create_family, join_by_invite


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
