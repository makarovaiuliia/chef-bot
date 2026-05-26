from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.fsm import PlanWizard
from bot.keyboards import kb_days, kb_draft_review, kb_meals_for_replace
from core import repositories
from core.db import Family
from core.exceptions import LLMError
from core.services import dish_replacer, menu_planner

router = Router()


def _format_menu(menu) -> str:
    lines = [
        f"<b>Меню на {menu.days_count} дн. с {menu.start_date.strftime('%d.%m.%Y')}:</b>",
        "",
    ]
    current_date = None
    for meal in menu.meals:
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


@router.message(Command("plan"))
async def cmd_plan(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PlanWizard.ask_days)
    await message.answer("На сколько дней планируем?", reply_markup=kb_days())


@router.callback_query(PlanWizard.ask_days, F.data.startswith("plan:days:"))
async def cb_days(cb: CallbackQuery, state: FSMContext) -> None:
    days = int(cb.data.split(":")[2])
    await state.update_data(days_count=days)
    await state.set_state(PlanWizard.ask_fridge)
    await cb.message.edit_text(
        f"{days} дней. Что уже есть в холодильнике? "
        "Перечисли через запятую (или напиши «ничего»)."
    )
    await cb.answer()


@router.message(PlanWizard.ask_fridge)
async def msg_fridge(
    message: Message,
    state: FSMContext,
    family: Family,
    db_session: AsyncSession,
) -> None:
    data = await state.get_data()
    days = data["days_count"]
    fridge_text = message.text or ""
    await message.answer("Генерирую меню, это займёт ~20 секунд...")
    try:
        menu = await menu_planner.start_planning(
            db_session,
            family_id=family.id,
            days_count=days,
            start_date=date.today(),
            fridge_text=fridge_text,
        )
    except LLMError as e:
        logger.exception("LLM failed: {}", e)
        await message.answer("Что-то пошло не так на стороне LLM. Попробуй /plan ещё раз.")
        await state.clear()
        return

    await state.update_data(menu_id=menu.id)
    await state.set_state(PlanWizard.draft_review)
    await message.answer(_format_menu(menu), reply_markup=kb_draft_review(menu.id))


@router.callback_query(PlanWizard.draft_review, F.data.startswith("plan:approve:"))
async def cb_approve(
    cb: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    menu_id = int(cb.data.split(":")[2])
    await menu_planner.approve(db_session, menu_id)
    await cb.message.edit_text(cb.message.html_text + "\n\n✅ Меню утверждено.")
    await state.clear()
    await cb.answer("Утверждено")


@router.callback_query(PlanWizard.draft_review, F.data.startswith("plan:cancel:"))
async def cb_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.message.edit_text("Отменено.")
    await state.clear()
    await cb.answer()


@router.callback_query(PlanWizard.draft_review, F.data.startswith("plan:replace_pick:"))
async def cb_replace_pick(
    cb: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    menu_id = int(cb.data.split(":")[2])
    menu = await repositories.get_menu_with_meals(db_session, menu_id)
    if menu is None:
        await cb.answer("Меню не найдено")
        return
    await state.set_state(PlanWizard.ask_which_meal)
    await cb.message.answer(
        "Какое блюдо заменить?", reply_markup=kb_meals_for_replace(menu.meals)
    )
    await cb.answer()


@router.callback_query(PlanWizard.ask_which_meal, F.data.startswith("plan:replace_meal:"))
async def cb_pick_meal(cb: CallbackQuery, state: FSMContext) -> None:
    meal_id = int(cb.data.split(":")[2])
    await state.update_data(meal_id_to_replace=meal_id)
    await state.set_state(PlanWizard.ask_replace_hint)
    await cb.message.answer(
        "Какое пожелание к новому блюду? (например, 'с рыбой', 'попроще', "
        "'без курицы'). Напиши свободным текстом или 'без пожеланий'."
    )
    await cb.answer()


@router.message(PlanWizard.ask_replace_hint)
async def msg_replace_hint(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    data = await state.get_data()
    meal_id = data["meal_id_to_replace"]
    menu_id = data["menu_id"]
    hint = message.text or "без пожеланий"
    await message.answer("Подбираю замену...")
    try:
        await dish_replacer.replace_meal(db_session, meal_id=meal_id, hint=hint)
    except LLMError as e:
        logger.exception("replace failed: {}", e)
        await message.answer("Не получилось. Попробуй ещё раз.")
        return

    menu = await repositories.get_menu_with_meals(db_session, menu_id)
    await state.set_state(PlanWizard.draft_review)
    await message.answer(
        "Готово, обновил:\n\n" + _format_menu(menu),
        reply_markup=kb_draft_review(menu_id),
    )
