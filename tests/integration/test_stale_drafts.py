"""Чистка осиротевших черновиков меню."""
from datetime import UTC, date, datetime, timedelta

from core.db import Menu, MenuStatus
from core.repositories import create_draft_menu, delete_stale_drafts, get_menu_with_meals
from core.services.family_service import create_family

START = date(2026, 7, 21)


async def _family(db_session):
    family, _ = await create_family(
        db_session,
        telegram_user_id=111,
        display_name="Юля",
        profile_md="# Профиль",
        timezone="UTC",
        plan_slots=["dinner"],
    )
    return family


async def _draft(db_session, family_id, *, created_at=None):
    menu = await create_draft_menu(
        db_session,
        family_id=family_id,
        start_date=START,
        days_count=1,
        meals=[
            {
                "date": START,
                "slot": "dinner",
                "dish_name": "Плов",
                "side_dishes": [],
                "protein_kind": "chicken",
            }
        ],
    )
    if created_at is not None:
        menu.created_at = created_at
        await db_session.flush()
    return menu


async def test_old_draft_is_removed(db_session):
    family = await _family(db_session)
    old = datetime.now(UTC) - timedelta(hours=48)
    menu = await _draft(db_session, family.id, created_at=old)

    removed = await delete_stale_drafts(
        db_session, older_than=datetime.now(UTC) - timedelta(hours=24)
    )

    assert removed == 1
    assert await get_menu_with_meals(db_session, menu.id) is None


async def test_fresh_draft_is_kept(db_session):
    """Юзер может прямо сейчас смотреть на этот черновик."""
    family = await _family(db_session)
    menu = await _draft(db_session, family.id)

    removed = await delete_stale_drafts(
        db_session, older_than=datetime.now(UTC) - timedelta(hours=24)
    )

    assert removed == 0
    assert await get_menu_with_meals(db_session, menu.id) is not None


async def test_approved_menu_is_never_removed(db_session):
    """Спека §7: строки menus не удаляются никогда — чистка только черновиков."""
    family = await _family(db_session)
    menu = await _draft(db_session, family.id, created_at=datetime.now(UTC) - timedelta(days=30))
    menu.status = MenuStatus.active
    await db_session.flush()

    removed = await delete_stale_drafts(db_session, older_than=datetime.now(UTC))

    assert removed == 0
    assert await get_menu_with_meals(db_session, menu.id) is not None


async def test_cleanup_cascades_to_meals(db_session):
    from sqlalchemy import func, select

    from core.db import Meal

    family = await _family(db_session)
    await _draft(db_session, family.id, created_at=datetime.now(UTC) - timedelta(days=2))

    await delete_stale_drafts(db_session, older_than=datetime.now(UTC) - timedelta(hours=24))

    meals_left = (await db_session.execute(select(func.count()).select_from(Meal))).scalar_one()
    menus_left = (await db_session.execute(select(func.count()).select_from(Menu))).scalar_one()
    assert (meals_left, menus_left) == (0, 0)


async def test_nothing_to_clean_is_fine(db_session):
    await _family(db_session)
    assert await delete_stale_drafts(db_session, older_than=datetime.now(UTC)) == 0
