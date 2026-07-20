from core.services.family_service import create_family, update_profile


async def test_update_profile(db_session):
    family, _ = await create_family(
        db_session,
        telegram_user_id=1,
        display_name="A",
        profile_md="старый",
        timezone="UTC",
        plan_slots=["dinner"],
    )
    await update_profile(db_session, family=family, profile_md="новый")
    assert family.profile_md == "новый"
