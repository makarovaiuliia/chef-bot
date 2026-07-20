from core.services.family_service import create_family, get_admin, join_by_invite


async def test_join_notifies_admin_target(db_session):
    family, admin = await create_family(
        db_session, telegram_user_id=1, display_name="Юля",
        profile_md="p", timezone="UTC", plan_slots=["dinner"],
    )
    _, member = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=2, display_name="Вова"
    )
    found_admin = await get_admin(db_session, family_id=family.id)
    assert found_admin.telegram_user_id == 1
    assert member.family_id == family.id
