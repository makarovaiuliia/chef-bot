from core import repositories
from core.services import shopping_list
from core.services.family_service import get_or_create_family


async def test_add_manual_item_creates_standalone_item(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)

    item = await shopping_list.add_manual_item(
        db_session, family_id=family.id, name="молоко"
    )

    assert item.shopping_list_id is None
    assert item.name == "молоко"
    assert item.quantity == ""
    assert item.store.value == "other"
    assert item.bought is False

    items = await repositories.get_open_shopping_items(db_session, family_id=family.id)
    assert len(items) == 1
    assert items[0].name == "молоко"


async def test_toggle_bought_round_trip(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)

    item = await shopping_list.add_manual_item(
        db_session, family_id=family.id, name="молоко"
    )

    toggled = await shopping_list.toggle_bought(db_session, item_id=item.id)
    assert toggled.bought is True

    items_after = await repositories.get_open_shopping_items(db_session, family_id=family.id)
    assert items_after == []
