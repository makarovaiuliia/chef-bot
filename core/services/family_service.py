import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import Family, FamilyMember, MemberRole
from core.exceptions import AlreadyInFamily, InvalidInviteCode, MemberNotInFamily


def _new_invite_code() -> str:
    return secrets.token_urlsafe(9)


def is_admin(member: FamilyMember) -> bool:
    return member.role == MemberRole.admin


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


async def update_profile(session: AsyncSession, *, family: Family, profile_md: str) -> None:
    family.profile_md = profile_md
    await session.flush()


async def get_admins(session: AsyncSession, *, family_id: int) -> list[FamilyMember]:
    stmt = (
        select(FamilyMember)
        .where(
            FamilyMember.family_id == family_id,
            FamilyMember.role == MemberRole.admin,
        )
        .order_by(FamilyMember.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_digest_settings(
    session: AsyncSession,
    *,
    family: Family,
    enabled: bool | None = None,
    hour: int | None = None,
) -> Family:
    """Настройки утреннего дайджеста (спека §5). Час — локальный для семьи."""
    if enabled is not None:
        family.digest_enabled = enabled
    if hour is not None:
        if not 5 <= hour <= 12:
            raise ValueError(f"digest_hour вне диапазона 5..12: {hour}")
        family.digest_hour = hour
    await session.flush()
    return family


async def grant_admin(
    session: AsyncSession, *, family_id: int, member_id: int
) -> FamilyMember:
    """Назначить участника администратором. Прежние админы права не теряют."""
    member = (
        await session.execute(
            select(FamilyMember).where(
                FamilyMember.id == member_id, FamilyMember.family_id == family_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise MemberNotInFamily
    member.role = MemberRole.admin
    await session.flush()
    return member
