from core.services import reminders, shopping_list
from core.services.family_service import get_or_create_family


async def test_reminder_none_when_empty(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    text = await reminders.build_shopping_reminder(db_session, family_id=family.id)
    assert text is None


async def test_reminder_counts_open_items(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    for name in ["молоко", "хлеб", "сыр"]:
        await shopping_list.add_manual_item(db_session, family_id=family.id, name=name)

    text = await reminders.build_shopping_reminder(db_session, family_id=family.id)

    assert text is not None
    assert "3" in text
    assert "/list" in text


async def test_reminder_skips_bought_items(db_session):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    items = [
        await shopping_list.add_manual_item(db_session, family_id=family.id, name=n)
        for n in ["молоко", "хлеб"]
    ]
    await shopping_list.toggle_bought(db_session, item_id=items[0].id)

    text = await reminders.build_shopping_reminder(db_session, family_id=family.id)

    assert text is not None
    assert "1 незакрытый пункт" in text
