from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import HasFamily
from bot.keyboards import BTN_TODAY, kb_meal_recipes, kb_want_subscription
from core import emoji, repositories
from core.db import Family, Meal
from core.exceptions import LimitExceeded, LLMError, MealNotFound
from core.meal_format import format_meal_lines
from core.ru_format import format_date_short
from core.services import limits, recipe_service
from core.services.limits import denial_text

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily())


def _empty_menu_text() -> str:
    return "Меню пока нет. Спланировать: /plan (доступно администратору семьи)."


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
        await message.answer(_empty_menu_text())
        return
    await message.answer(_format_future_meals(meals, today))


@router.message(Command("today"))
@router.message(F.text == BTN_TODAY)
async def cmd_today(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    today = date.today()
    meals = await repositories.get_meals_for_date(db_session, family.id, today)
    if not meals:
        await message.answer(f"На сегодня ничего не запланировано. {_empty_menu_text()}")
        return
    await message.answer(_format_today(meals, today), reply_markup=kb_meal_recipes(meals))


@router.callback_query(F.data.startswith("meal:recipe:"))
async def cb_recipe(cb: CallbackQuery, family: Family, db_session: AsyncSession) -> None:
    meal_id = int(cb.data.split(":")[-1])
    meal = await repositories.get_meal_for_family(db_session, meal_id, family_id=family.id)
    if meal is None:
        await cb.answer("Блюдо не найдено (меню обновилось?)", show_alert=True)
        return
    await cb.answer()
    placeholder = await cb.message.answer(f"{emoji.WAIT} Готовлю рецепт...")
    try:
        recipe = await recipe_service.get_recipe(
            db_session, meal_id=meal.id, profile_md=family.profile_md or "", family_id=family.id
        )
    except LimitExceeded as e:
        markup = None if limits.subscription_active(family) else kb_want_subscription()
        await placeholder.edit_text(denial_text(e), reply_markup=markup)
        return
    except LLMError:
        logger.exception("recipe generation failed meal_id={}", meal_id)
        await placeholder.edit_text("Не получилось приготовить рецепт. Нажмите кнопку еще раз.")
        return
    except MealNotFound:
        logger.warning("meal disappeared during recipe generation meal_id={}", meal_id)
        await placeholder.edit_text("Блюдо не найдено — меню обновилось. Откройте /menu заново.")
        return
    await placeholder.edit_text(recipe.content_md)  # content_md уже в Telegram HTML
