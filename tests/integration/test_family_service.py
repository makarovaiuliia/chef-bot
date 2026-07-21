import pytest

from core.exceptions import AlreadyInFamily, InvalidInviteCode, MemberNotInFamily
from core.services.family_service import (
    create_family,
    get_admins,
    grant_admin,
    is_admin,
    join_by_invite,
    regenerate_invite,
    resolve_member,
)


async def _make_family(db_session, tg_id=111):
    return await create_family(
        db_session,
        telegram_user_id=tg_id,
        display_name="Юля",
        profile_md="# Профиль",
        timezone="Asia/Bangkok",
        plan_slots=["lunch", "dinner"],
    )


async def test_create_family_sets_admin_and_invite(db_session):
    family, member = await _make_family(db_session)
    assert is_admin(member)
    assert family.invite_code
    assert family.profile_md == "# Профиль"
    assert family.plan_slots == ["lunch", "dinner"]


async def test_resolve_member_roundtrip(db_session):
    family, member = await _make_family(db_session)
    resolved = await resolve_member(db_session, 111)
    assert resolved is not None
    assert resolved[0].id == family.id
    assert await resolve_member(db_session, 999) is None


async def test_join_by_invite(db_session):
    family, _ = await _make_family(db_session)
    fam2, joined = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=222, display_name="Вова"
    )
    assert fam2.id == family.id
    assert not is_admin(joined)


async def test_join_invalid_code_raises(db_session):
    with pytest.raises(InvalidInviteCode):
        await join_by_invite(
            db_session, invite_code="nope", telegram_user_id=222, display_name=None
        )


async def test_join_twice_raises(db_session):
    family, _ = await _make_family(db_session)
    with pytest.raises(AlreadyInFamily):
        await join_by_invite(
            db_session, invite_code=family.invite_code, telegram_user_id=111, display_name=None
        )


async def test_grant_admin_keeps_old_admin_rights(db_session):
    family, admin = await _make_family(db_session)
    _, joined = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=222, display_name="Вова"
    )
    await grant_admin(db_session, family_id=family.id, member_id=joined.id)
    admins = await get_admins(db_session, family_id=family.id)
    assert {a.telegram_user_id for a in admins} == {111, 222}
    assert is_admin(admin) and is_admin(joined)  # прежний админ ничего не потерял


async def test_grant_admin_rejects_member_from_other_family(db_session):
    family, _ = await _make_family(db_session, tg_id=111)
    other_family, other_member = await _make_family(db_session, tg_id=333)
    with pytest.raises(MemberNotInFamily):
        await grant_admin(db_session, family_id=family.id, member_id=other_member.id)
    admins = await get_admins(db_session, family_id=family.id)
    assert len(admins) == 1


async def test_regenerate_invite_changes_code(db_session):
    family, _ = await _make_family(db_session)
    old = family.invite_code
    new = await regenerate_invite(db_session, family=family)
    assert new != old and family.invite_code == new
