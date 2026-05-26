from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core.db import Family, FamilyMember


def is_authorized(telegram_user_id: int) -> bool:
    return telegram_user_id in get_settings().allowlist_telegram_ids


async def get_or_create_family(
    session: AsyncSession,
    telegram_user_id: int,
    display_name: str | None = None,
) -> tuple[Family, FamilyMember]:
    """Shared-family mode: all allowlisted users share one Family."""
    member = (
        await session.execute(
            select(FamilyMember).where(FamilyMember.telegram_user_id == telegram_user_id)
        )
    ).scalar_one_or_none()
    if member is not None:
        family = (
            await session.execute(select(Family).where(Family.id == member.family_id))
        ).scalar_one()
        return family, member

    family = (await session.execute(select(Family).limit(1))).scalar_one_or_none()
    if family is None:
        family = Family(name="Family")
        session.add(family)
        await session.flush()

    member = FamilyMember(
        family_id=family.id,
        telegram_user_id=telegram_user_id,
        display_name=display_name,
    )
    session.add(member)
    await session.flush()
    return family, member
