"""Выход из семьи и удаление участника: правила и крайние случаи."""
import pytest

from core.exceptions import (
    CannotRemoveAdmin,
    LastAdminCannotLeave,
    MemberNotInFamily,
)
from core.repositories import get_family_members
from core.services.family_service import (
    create_family,
    grant_admin,
    is_admin,
    join_by_invite,
    leave_family,
    remove_member,
    resolve_member,
)


async def _family_with_member(db_session, member_tg=222):
    """Семья: админ (tg=111) + один обычный участник."""
    family, admin = await create_family(
        db_session,
        telegram_user_id=111,
        display_name="Юля",
        profile_md="# Профиль",
        timezone="Asia/Bangkok",
        plan_slots=["lunch", "dinner"],
    )
    _f, member = await join_by_invite(
        db_session,
        invite_code=family.invite_code,
        telegram_user_id=member_tg,
        display_name="Петя",
    )
    return family, admin, member


async def test_member_can_leave(db_session):
    family, _admin, member = await _family_with_member(db_session)
    await leave_family(db_session, family=family, member=member)
    left = [m.telegram_user_id for m in await get_family_members(db_session, family.id)]
    assert left == [111]
    # Ушедший больше не резолвится в семью — попадет в онбординг через /start.
    assert await resolve_member(db_session, 222) is None


async def test_leaving_member_does_not_clear_invite_code(db_session):
    family, _admin, member = await _family_with_member(db_session)
    code = family.invite_code
    await leave_family(db_session, family=family, member=member)
    assert family.invite_code == code


async def test_single_admin_cannot_leave_while_others_remain(db_session):
    family, admin, _member = await _family_with_member(db_session)
    with pytest.raises(LastAdminCannotLeave):
        await leave_family(db_session, family=family, member=admin)
    assert len(await get_family_members(db_session, family.id)) == 2


async def test_admin_can_leave_after_second_admin_appointed(db_session):
    family, admin, member = await _family_with_member(db_session)
    await grant_admin(db_session, family_id=family.id, member_id=member.id)
    await leave_family(db_session, family=family, member=admin)
    remaining = await get_family_members(db_session, family.id)
    assert [m.telegram_user_id for m in remaining] == [222]
    assert is_admin(remaining[0])


async def test_last_member_leaving_clears_invite_code(db_session):
    """Семья опустела — утекшая ссылка не должна пускать в семью без админов."""
    family, admin = await create_family(
        db_session,
        telegram_user_id=111,
        display_name="Юля",
        profile_md="# Профиль",
        timezone="Asia/Bangkok",
        plan_slots=["lunch"],
    )
    assert family.invite_code
    await leave_family(db_session, family=family, member=admin)
    assert family.invite_code is None
    assert await get_family_members(db_session, family.id) == []


async def test_admin_removes_member(db_session):
    family, admin, member = await _family_with_member(db_session)
    removed = await remove_member(
        db_session, family_id=family.id, actor=admin, member_id=member.id
    )
    assert removed.telegram_user_id == 222
    assert [m.telegram_user_id for m in await get_family_members(db_session, family.id)] == [111]


async def test_admin_cannot_remove_another_admin(db_session):
    family, admin, member = await _family_with_member(db_session)
    await grant_admin(db_session, family_id=family.id, member_id=member.id)
    with pytest.raises(CannotRemoveAdmin):
        await remove_member(
            db_session, family_id=family.id, actor=admin, member_id=member.id
        )
    assert len(await get_family_members(db_session, family.id)) == 2


async def test_admin_cannot_remove_self(db_session):
    family, admin, _member = await _family_with_member(db_session)
    with pytest.raises(CannotRemoveAdmin):
        await remove_member(
            db_session, family_id=family.id, actor=admin, member_id=admin.id
        )


async def test_cannot_remove_member_of_another_family(db_session):
    family, admin, _member = await _family_with_member(db_session)
    other_family, other_admin = await create_family(
        db_session,
        telegram_user_id=333,
        display_name="Сидоровы",
        profile_md="# Профиль",
        timezone="Europe/Moscow",
        plan_slots=["dinner"],
    )
    with pytest.raises(MemberNotInFamily):
        await remove_member(
            db_session, family_id=family.id, actor=admin, member_id=other_admin.id
        )
    assert len(await get_family_members(db_session, other_family.id)) == 1


async def test_remove_unknown_member_id(db_session):
    family, admin, _member = await _family_with_member(db_session)
    with pytest.raises(MemberNotInFamily):
        await remove_member(
            db_session, family_id=family.id, actor=admin, member_id=99999
        )
