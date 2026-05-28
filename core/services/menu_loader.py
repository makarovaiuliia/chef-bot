"""Load a pre-built menu from a JSON document. Menu is planned externally;
the bot only stores and serves it.

Each /load adds meals to the family's forward-looking calendar. If any of the
new meals' dates already have meals (on or after today), the caller must
confirm before overwriting — see preview_load / commit_load split."""
import json
from dataclasses import dataclass, field
from datetime import date as DateType

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Menu
from core.models import MealDTO


class MenuLoadError(Exception):
    pass


class MenuFile(BaseModel):
    start_date: DateType
    meals: list[MealDTO] = Field(min_length=1)


@dataclass
class LoadPreview:
    parsed: MenuFile
    conflicting_dates: set[DateType] = field(default_factory=set)


def parse_raw(raw: bytes) -> MenuFile:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise MenuLoadError(f"невалидный JSON ({e.msg})") from e
    try:
        return MenuFile.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise MenuLoadError(f"{loc}: {first['msg']}") from e


def _validate_range(parsed: MenuFile) -> None:
    last_date = max(m.date for m in parsed.meals)
    if last_date < parsed.start_date:
        raise MenuLoadError("start_date позже последней даты в meals")


async def preview_load(
    session: AsyncSession, *, family_id: int, raw: bytes, today: DateType
) -> LoadPreview:
    parsed = parse_raw(raw)
    _validate_range(parsed)
    dates = {m.date for m in parsed.meals}
    conflicts = await repositories.find_conflicting_meal_dates(
        session, family_id=family_id, dates=dates, from_date=today
    )
    return LoadPreview(parsed=parsed, conflicting_dates=conflicts)


async def commit_load(
    session: AsyncSession,
    *,
    family_id: int,
    parsed: MenuFile,
    today: DateType,
) -> Menu:
    """Insert the new meals. Any existing meals on the same future dates are
    deleted first (caller is expected to have confirmed with the user)."""
    _validate_range(parsed)
    overlap_dates = [m.date for m in parsed.meals]
    await repositories.delete_future_meals_on_dates(
        session, family_id=family_id, dates=overlap_dates, from_date=today
    )
    last_date = max(m.date for m in parsed.meals)
    days_count = (last_date - parsed.start_date).days + 1
    menu = await repositories.create_draft_menu(
        session,
        family_id=family_id,
        start_date=parsed.start_date,
        days_count=days_count,
        meals=[m.model_dump(mode="python") for m in parsed.meals],
    )
    await repositories.approve_menu(session, menu_id=menu.id)
    await session.refresh(menu, attribute_names=["meals"])
    return menu
