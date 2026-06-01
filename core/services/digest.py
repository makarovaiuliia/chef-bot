"""Morning digest: today + tomorrow meals, defrost nudge, shopping line.

Also appends a warning when the loaded menu has only 1–2 days left, so the
user knows it's time to load a new one.
"""
from datetime import date as DateType
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core import emoji, repositories
from core.db import Meal
from core.meal_format import format_meal_lines
from core.ru_format import format_date_short
from core.services import reminders


def _format_day_block(header: str, d: DateType, meals: list[Meal]) -> str:
    return "\n".join([f"{header} · {format_date_short(d)}", *format_meal_lines(meals)])


async def _build_end_of_menu_warning(
    session: AsyncSession, family_id: int, today: DateType
) -> str | None:
    future_meals = await repositories.get_future_meals(session, family_id, today)
    if not future_meals:
        return None
    last_date = max(m.date for m in future_meals)
    upcoming = (last_date - today).days
    if upcoming == 2:
        return f"{emoji.WARNING} Меню заканчивается через 2 дня — пора загрузить новое."
    if upcoming == 1:
        return f"{emoji.WARNING} Меню заканчивается завтра — пора загрузить новое."
    return None


async def build_morning_digest(
    session: AsyncSession, *, family_id: int, today: DateType
) -> str | None:
    """Build digest text or return None if no active menu / nothing to show."""
    today_meals = await repositories.get_meals_for_date(session, family_id, today)
    tomorrow = today + timedelta(days=1)
    tomorrow_meals = await repositories.get_meals_for_date(session, family_id, tomorrow)

    sections: list[str] = []
    if today_meals:
        sections.append(_format_day_block(f"{emoji.TODAY} Сегодня", today, today_meals))
    if tomorrow_meals:
        sections.append(
            _format_day_block(f"{emoji.TOMORROW} Завтра", tomorrow, tomorrow_meals)
        )

    footer: list[str] = []
    if today_meals or tomorrow_meals:
        warning = await _build_end_of_menu_warning(session, family_id, today)
        if warning:
            footer.append(warning)
        footer.append(f"{emoji.DEFROST} Разморозка на завтра?")

    shopping = await reminders.build_shopping_reminder(session, family_id=family_id)
    if shopping:
        footer.append(shopping)

    if footer:
        sections.append("\n".join(footer))

    if not sections:
        return None

    return "\n\n".join(sections)
