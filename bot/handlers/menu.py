from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from core import emoji, repositories
from core.db import Family, Meal
from core.meal_format import format_meal_lines
from core.ru_format import format_date_short

router = Router()


def _format_today(meals: list[Meal], today: date) -> str:
    header = f"{emoji.TODAY} Сегодня · {format_date_short(today)}"
    return "\n".join([header, *format_meal_lines(meals)])


def _format_future_meals(meals: list[Meal], today: date) -> str:
    last_date = max(m.date for m in meals)
    days = (last_date - today).days + 1
    sections = [f"<b>{emoji.MENU} Меню · {days} дн. с {today.strftime('%d.%m.%Y')}</b>"]
    for day in sorted({m.date for m in meals}):
        day_meals = [m for m in meals if m.date == day]
        block = [f"{emoji.TOMORROW} {format_date_short(day)}", *format_meal_lines(day_meals)]
        sections.append("\n".join(block))
    return "\n\n".join(sections)


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
    today = date.today()
    meals = await repositories.get_meals_for_date(db_session, family.id, today)
    if not meals:
        await message.answer(
            "На сегодня в меню ничего не запланировано. "
            "Пришли JSON-файл с меню."
        )
        return
    await message.answer(_format_today(meals, today))
