import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Family, FamilyMember, MemberRole
from core.exceptions import (
    AlreadyInFamily,
    CannotRemoveAdmin,
    InvalidInviteCode,
    LastAdminCannotLeave,
    LLMInvalidResponse,
    MemberNotInFamily,
)
from core.llm import LLMClient, load_prompt, parse_json_response
from core.services import limits
from core.services.onboarding import get_llm_client


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


async def leave_family(
    session: AsyncSession, *, family: Family, member: FamilyMember
) -> None:
    """Самовыход из семьи.

    Единственный админ уйти не может, пока в семье есть кто-то еще
    (LastAdminCannotLeave) — сначала пусть назначит второго админа в /family.
    Если ушел последний участник, обнуляем invite_code: по утекшей ссылке
    нельзя попасть в семью без админов. Данные семьи (меню, покупки) остаются —
    спека §7, строки menus не удаляются никогда.
    """
    members = await repositories.get_family_members(session, family.id)
    others = [m for m in members if m.id != member.id]
    if others and is_admin(member):
        remaining_admins = [m for m in others if is_admin(m)]
        if not remaining_admins:
            raise LastAdminCannotLeave
    await session.delete(member)
    if not others:
        family.invite_code = None
    await session.flush()


async def remove_member(
    session: AsyncSession, *, family_id: int, actor: FamilyMember, member_id: int
) -> FamilyMember:
    """Удаление участника администратором. Возвращает удаленного участника.

    Только role=member: другого админа удалять нельзя (CannotRemoveAdmin), себя
    тоже — для этого есть leave_family.
    """
    member = (
        await session.execute(
            select(FamilyMember).where(
                FamilyMember.id == member_id, FamilyMember.family_id == family_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise MemberNotInFamily
    if member.id == actor.id or is_admin(member):
        raise CannotRemoveAdmin
    await session.delete(member)
    await session.flush()
    return member


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


async def change_family_timezone(
    session: AsyncSession, *, family: Family, city: str, llm: LLMClient | None = None
) -> str | None:
    """Смена таймзоны семьи по городу через LLM (operation="tz_detect").

    None — город не распознан или LLM вернул невалидную IANA-зону; таймзона
    семьи в этом случае не меняется. Триал-лимита у операции нет (нет ключа
    в _trial_limits) — ensure_within_limits проверит только месячный потолок.
    """
    await limits.ensure_within_limits(session, family_id=family.id, operation="tz_detect")
    llm = llm or get_llm_client()
    system_blocks = [{"type": "text", "text": load_prompt("timezone_detector")}]
    messages = [{"role": "user", "content": f"Город: {city}"}]
    tokens_in = tokens_out = 0
    tz: str | None = None
    last_error: LLMInvalidResponse | None = None
    for _ in range(2):  # 1 попытка + 1 retry на невалидный JSON (как generate_profile)
        resp = await llm.chat(
            system_blocks=system_blocks, messages=messages, max_tokens=256
        )
        tokens_in += resp.tokens_in
        tokens_out += resp.tokens_out
        try:
            data = parse_json_response(resp.text)
        except LLMInvalidResponse as e:
            last_error = e
            continue
        raw = data.get("timezone")
        tz = str(raw) if raw else None
        last_error = None
        break
    await repositories.log_llm_usage(
        session, family_id=family.id, operation="tz_detect",
        tokens_in=tokens_in, tokens_out=tokens_out,
    )
    if last_error is not None:
        raise last_error
    if tz is None:
        return None
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
    family.timezone = tz
    await session.flush()
    return tz
