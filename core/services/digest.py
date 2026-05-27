"""Morning digest: today + tomorrow meals + static defrost reminder."""
from datetime import date as DateType
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Meal, MealSlot

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


async def build_morning_digest(
    session: AsyncSession, *, family_id: int, today: DateType
) -> str | None:
    """Build digest text or return None if no active menu / nothing to show."""
    today_meals = await repositories.get_meals_for_date(session, family_id, today)
    tomorrow = today + timedelta(days=1)
    tomorrow_meals = await repositories.get_meals_for_date(session, family_id, tomorrow)

    if not today_meals and not tomorrow_meals:
        return None

    blocks = []
    if today_meals:
        blocks.append(_format_day_block("🌅 Сегодня", today, today_meals))
    if tomorrow_meals:
        blocks.append(_format_day_block("📅 Завтра", tomorrow, tomorrow_meals))

    blocks.append("🥶 Не забудь поставить разморозку, если надо")
    return "\n\n".join(blocks)
