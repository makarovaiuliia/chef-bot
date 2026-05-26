from config import get_settings
from core.services.family_service import get_or_create_family, is_authorized


def test_unauthorized_telegram_id_returns_false():
    assert is_authorized(999) is False


def test_authorized_telegram_id_returns_true():
    get_settings.cache_clear()
    assert is_authorized(111) is True


async def test_get_or_create_family_creates_new(db_session):
    family, member = await get_or_create_family(
        db_session, telegram_user_id=111, display_name="Юля"
    )
    assert family.id is not None
    assert member.telegram_user_id == 111
    assert member.display_name == "Юля"
    assert member.family_id == family.id


async def test_get_or_create_family_returns_existing(db_session):
    f1, m1 = await get_or_create_family(
        db_session, telegram_user_id=111, display_name="Юля"
    )
    f2, m2 = await get_or_create_family(
        db_session, telegram_user_id=111, display_name="Юля"
    )
    assert f1.id == f2.id
    assert m1.id == m2.id
