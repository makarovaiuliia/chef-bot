from types import SimpleNamespace

from bot.filters import HasFamily, IsAdmin
from core.db import FamilyMember, MemberRole


async def test_has_family_false_when_none():
    assert await HasFamily()(SimpleNamespace(), family=None) is False


async def test_has_family_true():
    assert await HasFamily()(SimpleNamespace(), family=SimpleNamespace(id=1)) is True


async def test_is_admin():
    admin = FamilyMember(family_id=1, telegram_user_id=1, role=MemberRole.admin)
    member = FamilyMember(family_id=1, telegram_user_id=2, role=MemberRole.member)
    assert await IsAdmin()(SimpleNamespace(), family_member=admin) is True
    assert await IsAdmin()(SimpleNamespace(), family_member=member) is False
