import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import Family, FamilyMember, MemberRole
from core.exceptions import AlreadyInFamily, InvalidInviteCode


def _new_invite_code() -> str:
    return secrets.token_urlsafe(9)


def is_admin(member: FamilyMember) -> bool:
    return member.role == MemberRole.admin


def has_plan_rights(member: FamilyMember) -> bool:
    return is_admin(member) or member.can_plan


async def resolve_member(
    session: AsyncSession, telegram_user_id: int
) -> tuple[Family, FamilyMember] | None:
    member = (
        await session.execute(
            select(FamilyMember).where(FamilyMember.telegram_user_id == telegram_user_id)
        )
    ).scalar_one_or_none()
    if member is None:
        return None
    family = (
        await session.execute(select(Family).where(Family.id == member.family_id))
    ).scalar_one()
    return family, member


async def create_family(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    display_name: str | None,
    profile_md: str,
    timezone: str,
    plan_slots: list[str],
) -> tuple[Family, FamilyMember]:
    family = Family(
        name=display_name or "Семья",
        profile_md=profile_md,
        timezone=timezone,
        plan_slots=plan_slots,
        invite_code=_new_invite_code(),
    )
    session.add(family)
    await session.flush()
    member = FamilyMember(
        family_id=family.id,
        telegram_user_id=telegram_user_id,
        display_name=display_name,
        role=MemberRole.admin,
        can_plan=True,
    )
    session.add(member)
    await session.flush()
    return family, member


async def join_by_invite(
    session: AsyncSession,
    *,
    invite_code: str,
    telegram_user_id: int,
    display_name: str | None,
) -> tuple[Family, FamilyMember]:
    if await resolve_member(session, telegram_user_id) is not None:
        raise AlreadyInFamily
    family = (
        await session.execute(select(Family).where(Family.invite_code == invite_code))
    ).scalar_one_or_none()
    if family is None:
        raise InvalidInviteCode
    member = FamilyMember(
        family_id=family.id,
        telegram_user_id=telegram_user_id,
        display_name=display_name,
    )
    session.add(member)
    await session.flush()
    return family, member


async def regenerate_invite(session: AsyncSession, *, family: Family) -> str:
    family.invite_code = _new_invite_code()
    await session.flush()
    return family.invite_code


async def set_can_plan(
    session: AsyncSession, *, member_id: int, value: bool
) -> FamilyMember:
    member = (
        await session.execute(select(FamilyMember).where(FamilyMember.id == member_id))
    ).scalar_one()
    member.can_plan = value
    await session.flush()
    return member


async def get_admin(session: AsyncSession, *, family_id: int) -> FamilyMember | None:
    return (
        await session.execute(
            select(FamilyMember).where(
                FamilyMember.family_id == family_id,
                FamilyMember.role == MemberRole.admin,
            )
        )
    ).scalar_one_or_none()


async def transfer_admin(
    session: AsyncSession, *, family_id: int, to_member_id: int
) -> None:
    current = await get_admin(session, family_id=family_id)
    if current is not None:
        current.role = MemberRole.member
    new_admin = (
        await session.execute(select(FamilyMember).where(FamilyMember.id == to_member_id))
    ).scalar_one()
    new_admin.role = MemberRole.admin
    new_admin.can_plan = True
    await session.flush()
