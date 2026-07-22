"""Генерация меню в боте: черновик по профилю семьи → правки → утверждение."""
from datetime import date as DateType
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.constants import MENU_MAX_DAYS
from core.db import Family, MealSlot, Menu, MenuStatus
from core.exceptions import LLMInvalidResponse, MenuTooLong
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.meal_format import slot_label
from core.models import MealDTO
from core.services import limits


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


class _MenuSchema(BaseModel):
    meals: list[MealDTO] = Field(min_length=1)


def family_today(family: Family) -> DateType:
    try:
        tz = ZoneInfo(family.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def next_monday(today: DateType) -> DateType:
    return today if today.weekday() == 0 else today + timedelta(days=7 - today.weekday())


def parse_start_date(text: str, today: DateType) -> DateType | None:
    text = text.strip()
    parsed: DateType | None = None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.strptime(text, "%d.%m").date().replace(year=today.year)
            if parsed < today:
                parsed = parsed.replace(year=today.year + 1)
        except ValueError:
            return None
    return parsed if parsed >= today else None


def _user_message(family: Family, dates: list[DateType]) -> str:
    slots = family.plan_slots or ["lunch", "dinner"]
    slot_names = ", ".join(slot_label(MealSlot(s)) for s in slots)
    date_lines = "\n".join(f"- {d.isoformat()} ({d.strftime('%a')})" for d in dates)
    return (
        f"Составь меню на {len(dates)} дн.\n"
        f"Приемы пищи: {slot_names} (slot-значения: {', '.join(slots)}).\n"
        f"Даты:\n{date_lines}"
    )


def _validate_generated(parsed: _MenuSchema, dates: list[DateType], slots: list[str]) -> None:
    allowed_dates = set(dates)
    seen: set[tuple[DateType, str]] = set()
    for m in parsed.meals:
        if m.date not in allowed_dates:
            raise LLMInvalidResponse(f"meal date {m.date} вне запрошенного диапазона")
        if m.slot.value not in slots:
            raise LLMInvalidResponse(f"slot {m.slot.value} не входит в plan_slots семьи")
        key = (m.date, m.slot.value)
        if key in seen:
            raise LLMInvalidResponse(f"дубликат {m.date} {m.slot.value} в ответе LLM")
        seen.add(key)
    expected = len(dates) * len(slots)
    if len(seen) != expected:
        raise LLMInvalidResponse(f"неполное меню: {len(seen)} блюд вместо {expected}")


async def generate_menu(
    session: AsyncSession,
    *,
    family: Family,
    start_date: DateType,
    days_count: int,
    llm: LLMClient | None = None,
) -> Menu:
    """Черновик меню от LLM. 1 авто-retry на невалидный JSON; usage — при успехе."""
    if not 1 <= days_count <= MENU_MAX_DAYS:
        raise MenuTooLong(f"меню не длиннее {MENU_MAX_DAYS} дней")
    await limits.ensure_within_limits(session, family_id=family.id, operation="menu_gen")
    slots = family.plan_slots or ["lunch", "dinner"]
    dates = [start_date + timedelta(days=i) for i in range(days_count)]
    llm = llm or get_llm_client()

    messages = [{"role": "user", "content": _user_message(family, dates)}]
    system_blocks = build_system_blocks("menu_planner", profile_md=family.profile_md or "")
    tokens_in = tokens_out = 0
    last_error: LLMInvalidResponse | None = None
    for _ in range(2):  # 1 попытка + 1 retry (спека §8)
        resp = await llm.chat(system_blocks=system_blocks, messages=messages, max_tokens=4096)
        tokens_in += resp.tokens_in
        tokens_out += resp.tokens_out
        try:
            parsed = _MenuSchema.model_validate(parse_json_response(resp.text))
            _validate_generated(parsed, dates, slots)
        except (LLMInvalidResponse, ValueError) as e:
            last_error = e if isinstance(e, LLMInvalidResponse) else LLMInvalidResponse(str(e))
            continue
        menu = await repositories.create_draft_menu(
            session,
            family_id=family.id,
            start_date=start_date,
            days_count=days_count,
            meals=[m.model_dump(mode="python") for m in parsed.meals],
        )
        await repositories.log_llm_usage(
            session,
            family_id=family.id,
            operation="menu_gen",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        return menu
    assert last_error is not None
    raise last_error


async def delete_draft(session: AsyncSession, *, menu_id: int) -> None:
    menu = await session.get(Menu, menu_id)
    if menu is not None and menu.status == MenuStatus.draft:
        await session.delete(menu)
        await session.flush()


async def preview_approve(
    session: AsyncSession, *, menu: Menu, today: DateType
) -> set[DateType]:
    """Даты, на которых у семьи уже есть активные meals (конфликт при утверждении)."""
    return await repositories.find_conflicting_meal_dates(
        session,
        family_id=menu.family_id,
        dates={m.date for m in menu.meals},
        from_date=today,
    )


async def commit_approve(session: AsyncSession, *, menu: Menu, today: DateType) -> None:
    """Активирует черновик, перезаписывая чужие активные meals на его датах."""
    await repositories.delete_future_meals_on_dates(
        session,
        family_id=menu.family_id,
        dates=[m.date for m in menu.meals],
        from_date=today,
    )
    await repositories.approve_menu(session, menu.id)
