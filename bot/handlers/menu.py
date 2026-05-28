from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Family, Meal

router = Router()


def _format_future_meals(meals: list[Meal], today: date) -> str:
    last_date = max(m.date for m in meals)
    days = (last_date - today).days + 1
    lines = [
        f"<b>Меню на {days} дн. с {today.strftime('%d.%m.%Y')}:</b>",
        "",
    ]
    current_date = None
    for meal in meals:
        if meal.date != current_date:
            lines.append(f"\n<b>{meal.date.strftime('%a %d.%m')}</b>")
            current_date = meal.date
        slot_ru = "Обед" if meal.slot.value == "lunch" else "Ужин"
        sides = ", ".join(meal.side_dishes) if meal.side_dishes else ""
        line = f"  • {slot_ru}: {meal.dish_name}"
        if sides:
            line += f" + {sides}"
        lines.append(line)
    return "\n".join(lines)


@router.message(Command("menu"))
async def cmd_menu(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    today = date.today()
    meals = await repositories.get_future_meals(db_session, family.id, today)
    if not meals:
        await message.answer(
            "Меню не загружено. Пришли JSON-файл с меню."
        )
        return
    await message.answer(_format_future_meals(meals, today))


@router.message(Command("today"))
async def cmd_today(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    meals = await repositories.get_meals_for_date(db_session, family.id, date.today())
    if not meals:
        await message.answer(
            "На сегодня в меню ничего не запланировано. "
            "Пришли JSON-файл с меню."
        )
        return
    lines = [f"<b>Сегодня ({date.today().strftime('%d.%m.%Y')}):</b>", ""]
    for m in meals:
        slot_ru = "Обед" if m.slot.value == "lunch" else "Ужин"
        sides = ", ".join(m.side_dishes) if m.side_dishes else ""
        line = f"<b>{slot_ru}:</b> {m.dish_name}"
        if sides:
            line += f" + {sides}"
        lines.append(line)
    await message.answer("\n".join(lines))
