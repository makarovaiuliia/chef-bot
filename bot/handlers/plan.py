"""Флоу /plan: дата -> длительность -> LLM-черновик -> правки -> утверждение."""
import html
from datetime import date as DateType
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import HasFamily, IsAdmin
from bot.fsm import PlanFlow
from bot.keyboards import (
    BTN_ADD,
    BTN_FAMILY,
    BTN_TODAY,
    kb_plan_draft,
    kb_plan_duration,
    kb_plan_start,
    kb_retry,
)
from config import get_settings
from core import emoji
from core.db import Family, FamilyMember, Menu
from core.exceptions import LLMError
from core.meal_format import format_meal_lines
from core.ru_format import format_date_short
from core.services import menu_planner
from core.services.family_service import get_admins

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily(), IsAdmin())


def _planning_enabled() -> bool:
    return get_settings().planning_enabled


async def _planning_disabled_filter(message: Message) -> bool:
    return not _planning_enabled()


@router.message(Command("plan"), _planning_disabled_filter)
async def cmd_plan_disabled(message: Message) -> None:
    """Фича-флаг выключен: бот раздается до готовности планирования (спека §3)."""
    await message.answer(
        f"{emoji.MENU} Планирование меню в боте скоро появится. "
        "Пока меню загружает администратор семьи."
    )


@router.message(Command("plan"), IsAdmin())
async def cmd_plan(message: Message, state: FSMContext, family: Family) -> None:
    await state.clear()
    await state.set_state(PlanFlow.start_date)
    await message.answer("С какого дня планируем меню?", reply_markup=kb_plan_start())


@router.message(Command("plan"))
async def cmd_plan_denied(message: Message, db_session: AsyncSession, family: Family) -> None:
    admins = await get_admins(db_session, family_id=family.id)
    names = ", ".join(_actor_name(a) for a in admins) or "администратор"
    await message.answer(
        f"Планировать меню могут только администраторы ({names}). "
        "Попросите назначить вас администратором в /family."
    )


@router.callback_query(PlanFlow.start_date, F.data.startswith("plan:date:"))
async def on_start_date(cb: CallbackQuery, state: FSMContext, family: Family) -> None:
    choice = cb.data.split(":")[-1]
    today = menu_planner.family_today(family)
    if choice == "custom":
        await state.set_state(PlanFlow.custom_date)
        await cb.message.answer(
            "Напишите дату старта (например, 28.07):",
            reply_markup=ForceReply(input_field_placeholder="ДД.ММ или ДД.ММ.ГГГГ"),
        )
        await cb.answer()
        return
    start = {
        "today": today,
        "tomorrow": today + timedelta(days=1),
        "monday": menu_planner.next_monday(today),
    }[choice]
    await _ask_duration(cb.message, state, start)
    await cb.answer()


@router.message(
    PlanFlow.custom_date,
    F.text,
    ~F.text.in_({BTN_ADD, BTN_TODAY, BTN_FAMILY}),
)
async def on_custom_date(message: Message, state: FSMContext, family: Family) -> None:
    today = menu_planner.family_today(family)
    start = menu_planner.parse_start_date(message.text or "", today)
    if start is None:
        await message.answer(
            "Не понял дату. Формат: ДД.ММ или ДД.ММ.ГГГГ, не в прошлом. Попробуйте еще раз.",
            reply_markup=ForceReply(input_field_placeholder="например, 28.07"),
        )
        return
    await _ask_duration(message, state, start)


async def _ask_duration(message: Message, state: FSMContext, start: DateType) -> None:
    await state.update_data(start_date=start.isoformat())
    await state.set_state(PlanFlow.duration)
    await message.answer(
        f"Старт: {format_date_short(start)}. На сколько дней?",
        reply_markup=kb_plan_duration(),
    )


@router.callback_query(PlanFlow.duration, F.data.startswith("plan:days:"))
async def on_duration(
    cb: CallbackQuery,
    state: FSMContext,
    family: Family,
    family_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    await state.update_data(days=int(cb.data.split(":")[-1]))
    await cb.answer()
    await _generate_and_show(cb.message, state, family, family_member, db_session)


def _format_draft(menu: Menu) -> str:
    sections = [
        f"<b>{emoji.MENU} Черновик меню · {menu.days_count} дн. с "
        f"{menu.start_date.strftime('%d.%m.%Y')}</b>"
    ]
    for day in sorted({m.date for m in menu.meals}):
        day_meals = [m for m in menu.meals if m.date == day]
        sections.append(
            "\n".join([f"{emoji.TOMORROW} {format_date_short(day)}", *format_meal_lines(day_meals)])
        )
    return "\n\n".join(sections)


async def _generate_and_show(
    message: Message,
    state: FSMContext,
    family: Family,
    family_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    data = await state.get_data()
    start = DateType.fromisoformat(data["start_date"])
    days = data["days"]
    placeholder = await message.answer(f"{emoji.WAIT} Готовлю меню...")
    try:
        menu = await menu_planner.generate_menu(
            db_session, family=family, start_date=start, days_count=days
        )
    except LLMError:  # LLMInvalidResponse — подкласс; авто-retry уже был внутри
        logger.exception("plan: menu generation failed family_id={}", family.id)
        await state.set_state(PlanFlow.duration)
        await placeholder.edit_text(
            "Не получилось сгенерировать меню.",
            reply_markup=kb_retry(f"plan:days:{days}"),
        )
        return
    await state.update_data(menu_id=menu.id)
    await state.set_state(PlanFlow.draft)
    await placeholder.edit_text(_format_draft(menu), reply_markup=kb_plan_draft())
    await _notify_admins(
        message, db_session, family, family_member,
        f"{emoji.MENU} {_actor_name(family_member)} сгенерировал(а) черновик меню "
        f"на {days} дн. с {start.strftime('%d.%m.%Y')}",
    )


def _actor_name(member: FamilyMember) -> str:
    return html.escape(member.display_name) if member.display_name else str(member.telegram_user_id)


async def _notify_admins(
    message: Message,
    db_session: AsyncSession,
    family: Family,
    actor: FamilyMember,
    text: str,
) -> None:
    """Спека §4: о генерации/утверждении меню уведомляются остальные админы."""
    for admin in await get_admins(db_session, family_id=family.id):
        if admin.telegram_user_id == actor.telegram_user_id:
            continue
        try:
            await message.bot.send_message(admin.telegram_user_id, text)
        except Exception:
            logger.warning(
                "plan: admin notification failed admin_id={}", admin.telegram_user_id
            )
