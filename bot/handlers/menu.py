from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.plan import _format_menu
from core import repositories
from core.db import Family

router = Router()


@router.message(Command("menu"))
async def cmd_menu(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    menu = await repositories.get_active_menu(db_session, family.id)
    if menu is None:
        await message.answer("Активного меню нет. Запусти /plan, чтобы создать.")
        return
    await message.answer(_format_menu(menu))


@router.message(Command("today"))
async def cmd_today(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    meals = await repositories.get_meals_for_date(db_session, family.id, date.today())
    if not meals:
        await message.answer(
            "На сегодня в активном меню ничего не запланировано. Запусти /plan."
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
