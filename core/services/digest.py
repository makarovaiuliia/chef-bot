"""Morning digest: today + tomorrow meals + static defrost reminder.

Also appends a warning when the loaded menu has only 1–2 days left, so the
user knows it's time to load a new one, and the open shopping-list reminder.
"""
from datetime import date as DateType
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Meal, MealSlot
from core.services import reminders

_WEEKDAYS_RU = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]
_MONTHS_RU_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
_SLOT_LABEL = {MealSlot.lunch: "🍴 Обед", MealSlot.dinner: "🍽 Ужин"}


def _format_date_ru(d: DateType) -> str:
    return f"{_WEEKDAYS_RU[d.weekday()]}, {d.day} {_MONTHS_RU_GENITIVE[d.month - 1]}"


def _format_day_block(header: str, d: DateType, meals: list[Meal]) -> str:
    lines = [f"{header} ({_format_date_ru(d)})"]
    for slot in (MealSlot.lunch, MealSlot.dinner):
        meal = next((m for m in meals if m.slot == slot), None)
        if meal is not None:
            lines.append(f"{_SLOT_LABEL[slot]}: {meal.dish_name}")
    return "\n".join(lines)


async def _build_end_of_menu_warning(
    session: AsyncSession, family_id: int, today: DateType
) -> str | None:
    future_meals = await repositories.get_future_meals(session, family_id, today)
    if not future_meals:
        return None
    last_date = max(m.date for m in future_meals)
    upcoming = (last_date - today).days
    if upcoming == 2:
        return "⏳ Меню заканчивается через 2 дня — пора загрузить новое."
    if upcoming == 1:
        return "⏳ Меню заканчивается завтра — пора загрузить новое."
    return None


async def build_morning_digest(
    session: AsyncSession, *, family_id: int, today: DateType
) -> str | None:
    """Build digest text or return None if no active menu / nothing to show."""
    today_meals = await repositories.get_meals_for_date(session, family_id, today)
    tomorrow = today + timedelta(days=1)
    tomorrow_meals = await repositories.get_meals_for_date(session, family_id, tomorrow)

    blocks = []
    if today_meals or tomorrow_meals:
        if today_meals:
            blocks.append(_format_day_block("🌅 Сегодня", today, today_meals))
        if tomorrow_meals:
            blocks.append(_format_day_block("📅 Завтра", tomorrow, tomorrow_meals))

        blocks.append("🥶 Не забудь поставить разморозку, если надо")

        warning = await _build_end_of_menu_warning(session, family_id, today)
        if warning:
            blocks.append(warning)

    shopping = await reminders.build_shopping_reminder(session, family_id=family_id)
    if shopping:
        blocks.append(shopping)

    if not blocks:
        return None

    return "\n\n".join(blocks)
