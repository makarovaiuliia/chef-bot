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
    kb_plan_alternatives,
    kb_plan_approve_confirm,
    kb_plan_draft,
    kb_plan_duration,
    kb_plan_meals,
    kb_plan_start,
    kb_retry,
    kb_shoplist_offer,
    kb_want_subscription,
)
from core import emoji, repositories
from core.db import Family, FamilyMember, Menu, MenuStatus
from core.exceptions import LimitExceeded, LLMError, MealNotFound
from core.meal_format import format_dish_with_sides, format_meal_lines, slot_label
from core.ru_format import format_date_short
from core.services import limits, menu_planner, shopping_list
from core.services.dish_replacer import (
    ReplacementOption,
    apply_replacement,
    suggest_replacements,
)
from core.services.family_service import get_admins
from core.services.limits import denial_text

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily(), IsAdmin())


async def _start_plan_flow(message: Message, state: FSMContext, db_session: AsyncSession) -> None:
    """Общий вход в PlanFlow.start_date: чистит сиротский черновик перед стартом."""
    data = await state.get_data()
    orphan_id = data.get("menu_id")
    if orphan_id:
        await menu_planner.delete_draft(db_session, menu_id=orphan_id)
    await state.clear()
    await state.set_state(PlanFlow.start_date)
    await message.answer("С какого дня планируем меню?", reply_markup=kb_plan_start())


@router.message(Command("plan"), IsAdmin())
async def cmd_plan(
    message: Message, state: FSMContext, family: Family, db_session: AsyncSession
) -> None:
    await _start_plan_flow(message, state, db_session)


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
    ~F.text.startswith("/"),
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
    days = int(cb.data.split(":")[-1])
    if days not in {3, 5, 7}:
        await cb.answer("Недоступная длительность", show_alert=True)
        return
    await state.update_data(days=days)
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
    except LimitExceeded as e:
        await state.clear()
        markup = None if limits.subscription_active(family) else kb_want_subscription()
        await placeholder.edit_text(denial_text(e), reply_markup=markup)
        return
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


async def _draft_menu(state: FSMContext, db_session: AsyncSession, family: Family) -> Menu | None:
    data = await state.get_data()
    menu_id = data.get("menu_id")
    if menu_id is None:
        return None
    menu = await repositories.get_menu_with_meals(db_session, menu_id)
    return menu if menu is not None and menu.family_id == family.id else None


async def _show_draft(message: Message, state: FSMContext, menu: Menu) -> None:
    await state.set_state(PlanFlow.draft)
    await message.edit_text(_format_draft(menu), reply_markup=kb_plan_draft())


@router.callback_query(PlanFlow.draft, F.data == "plan:replace")
async def on_replace(
    cb: CallbackQuery, state: FSMContext, family: Family, db_session: AsyncSession
) -> None:
    menu = await _draft_menu(state, db_session, family)
    if menu is None:
        await cb.answer("Черновик не найден — начните заново: /plan", show_alert=True)
        return
    await state.set_state(PlanFlow.replace_pick)
    await cb.message.edit_text("Какое блюдо заменить?", reply_markup=kb_plan_meals(menu.meals))
    await cb.answer()


@router.callback_query(PlanFlow.replace_pick, F.data.startswith("plan:rm:"))
async def on_pick_meal(
    cb: CallbackQuery, state: FSMContext, family: Family, db_session: AsyncSession
) -> None:
    meal_id = int(cb.data.split(":")[-1])
    await state.update_data(replace_meal_id=meal_id)
    await cb.answer()
    await _suggest_and_show(cb.message, state, family, db_session, hint=None)


@router.message(
    PlanFlow.replace_hint,
    F.text,
    ~F.text.in_({BTN_ADD, BTN_TODAY, BTN_FAMILY}),
    ~F.text.startswith("/"),
)
async def on_replace_hint(
    message: Message, state: FSMContext, family: Family, db_session: AsyncSession
) -> None:
    # скоуп-ограниченный ввод: одна строка пожелания, не свободный чат (спека §3)
    await _suggest_and_show(message, state, family, db_session, hint=message.text.strip())


async def _suggest_and_show(
    message: Message,
    state: FSMContext,
    family: Family,
    db_session: AsyncSession,
    *,
    hint: str | None,
) -> None:
    data = await state.get_data()
    meal_id = data["replace_meal_id"]
    meal = await repositories.get_meal_for_family(db_session, meal_id, family_id=family.id)
    if meal is None:
        await message.answer("Блюдо не найдено — начните заново: /plan")
        return
    placeholder = await message.answer(f"{emoji.WAIT} Подбираю варианты...")
    try:
        options = await suggest_replacements(
            db_session,
            meal_id=meal_id,
            hint=hint,
            profile_md=family.profile_md or "",
            family_id=family.id,
        )
    except LimitExceeded as e:
        await state.clear()
        markup = None if limits.subscription_active(family) else kb_want_subscription()
        await placeholder.edit_text(denial_text(e), reply_markup=markup)
        return
    except LLMError:
        logger.exception("plan: suggest replacements failed meal_id={}", meal_id)
        await placeholder.edit_text("Не получилось подобрать замену. Выберите блюдо еще раз.")
        await state.set_state(PlanFlow.replace_pick)
        return
    await state.update_data(alternatives=[o.model_dump(mode="json") for o in options])
    await state.set_state(PlanFlow.replace_alts)
    lines = [f"Замена для «{meal.dish_name}» ({slot_label(meal.slot)}):", ""]
    for i, o in enumerate(options, 1):
        lines.append(f"<b>{i}.</b> {format_dish_with_sides(o.dish_name, o.side_dishes)}")
    await placeholder.edit_text("\n".join(lines), reply_markup=kb_plan_alternatives(len(options)))


@router.callback_query(PlanFlow.replace_alts, F.data.startswith("plan:alt:"))
@router.callback_query(PlanFlow.replace_hint, F.data.startswith("plan:alt:"))
async def on_pick_alternative(
    cb: CallbackQuery, state: FSMContext, family: Family, db_session: AsyncSession
) -> None:
    idx = int(cb.data.split(":")[-1])
    data = await state.get_data()
    raw = data.get("alternatives", [])
    if idx < 0 or idx >= len(raw):
        await cb.answer("Вариант не найден", show_alert=True)
        return
    option = ReplacementOption.model_validate(raw[idx])
    try:
        await apply_replacement(db_session, meal_id=data["replace_meal_id"], option=option)
    except (MealNotFound, ValueError):
        logger.warning(
            "plan: apply_replacement failed meal_id={}", data.get("replace_meal_id")
        )
        await cb.answer(
            "Блюдо не найдено — черновик изменился. /plan", show_alert=True
        )
        return
    menu = await _draft_menu(state, db_session, family)
    if menu is None:
        await cb.answer("Черновик не найден — начните заново: /plan", show_alert=True)
        return
    await cb.answer(f"Заменил на: {option.dish_name}")
    await _show_draft(cb.message, state, menu)


@router.callback_query(PlanFlow.replace_alts, F.data == "plan:althint")
async def on_ask_hint(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PlanFlow.replace_hint)
    await cb.message.answer(
        "Опишите пожелание одной строкой (например, «что-то с рыбой, побыстрее»):",
        reply_markup=ForceReply(input_field_placeholder="ваше пожелание"),
    )
    await cb.answer()


@router.callback_query(PlanFlow.replace_pick, F.data == "plan:back")
@router.callback_query(PlanFlow.replace_alts, F.data == "plan:back")
@router.callback_query(PlanFlow.replace_hint, F.data == "plan:back")
async def on_back_to_draft(
    cb: CallbackQuery, state: FSMContext, family: Family, db_session: AsyncSession
) -> None:
    menu = await _draft_menu(state, db_session, family)
    if menu is None:
        await cb.answer("Черновик не найден — начните заново: /plan", show_alert=True)
        return
    await cb.answer()
    await _show_draft(cb.message, state, menu)


@router.callback_query(PlanFlow.draft, F.data == "plan:regen")
async def on_regenerate(
    cb: CallbackQuery,
    state: FSMContext,
    family: Family,
    family_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    # отдельная генерация в лимитах (спека §3); старый черновик удаляем
    data = await state.get_data()
    if data.get("menu_id"):
        await menu_planner.delete_draft(db_session, menu_id=data["menu_id"])
    await cb.answer()
    await _generate_and_show(cb.message, state, family, family_member, db_session)


@router.callback_query(PlanFlow.draft, F.data == "plan:approve")
async def on_approve(cb: CallbackQuery, state: FSMContext, family: Family,
                     family_member: FamilyMember, db_session: AsyncSession) -> None:
    menu = await _draft_menu(state, db_session, family)
    if menu is None:
        await cb.answer("Черновик не найден — начните заново: /plan", show_alert=True)
        return
    today = menu_planner.family_today(family)
    conflicts = await menu_planner.preview_approve(db_session, menu=menu, today=today)
    if conflicts:
        dates_str = ", ".join(d.strftime("%d.%m.%Y") for d in sorted(conflicts))
        await state.set_state(PlanFlow.approve_confirm)
        await cb.message.edit_text(
            f"На даты {dates_str} уже есть меню. Перезаписать?",
            reply_markup=kb_plan_approve_confirm(),
        )
        await cb.answer()
        return
    await cb.answer()
    await _do_approve(cb.message, state, family, family_member, db_session, menu, today)


@router.callback_query(PlanFlow.approve_confirm, F.data == "plan:approveyes")
async def on_approve_yes(cb: CallbackQuery, state: FSMContext, family: Family,
                         family_member: FamilyMember, db_session: AsyncSession) -> None:
    menu = await _draft_menu(state, db_session, family)
    if menu is None:
        await cb.answer("Черновик не найден — начните заново: /plan", show_alert=True)
        return
    await cb.answer()
    await _do_approve(
        cb.message, state, family, family_member, db_session,
        menu, menu_planner.family_today(family),
    )


@router.callback_query(PlanFlow.approve_confirm, F.data == "plan:approveno")
async def on_approve_no(cb: CallbackQuery, state: FSMContext, family: Family,
                        db_session: AsyncSession) -> None:
    menu = await _draft_menu(state, db_session, family)
    await cb.answer()
    if menu is not None:
        await _show_draft(cb.message, state, menu)


async def _do_approve(message: Message, state: FSMContext, family: Family,
                      family_member: FamilyMember, db_session: AsyncSession,
                      menu: Menu, today) -> None:
    await menu_planner.commit_approve(db_session, menu=menu, today=today)
    await state.clear()
    await message.edit_text(
        f"{emoji.DONE} Меню утверждено: {menu.days_count} дн. с "
        f"{menu.start_date.strftime('%d.%m.%Y')}. Смотреть: /menu"
    )
    await _notify_admins(
        message, db_session, family, family_member,
        f"{emoji.DONE} {_actor_name(family_member)} утвердил(а) меню на "
        f"{menu.days_count} дн. с {menu.start_date.strftime('%d.%m.%Y')}",
    )
    await message.answer(
        f"{emoji.SHOPPING} Составить список покупок по меню?",
        reply_markup=kb_shoplist_offer(menu.id),
    )


async def _build_shopping(message: Message, family: Family,
                          db_session: AsyncSession, menu: Menu) -> None:
    placeholder = await message.answer(f"{emoji.SHOPPING} Собираю список покупок...")
    try:
        items = await shopping_list.build_from_menu(
            db_session, family_id=family.id, menu=menu, profile_md=family.profile_md or ""
        )
    except LimitExceeded as e:
        markup = None if limits.subscription_active(family) else kb_want_subscription()
        await placeholder.edit_text(denial_text(e), reply_markup=markup)
        return
    except LLMError:
        logger.exception("plan: shopping list build failed menu_id={}", menu.id)
        await placeholder.edit_text(
            "Меню утверждено, но список покупок собрать не получилось.",
            reply_markup=kb_retry(f"plan:shoplist:{menu.id}"),
        )
        return
    await placeholder.edit_text(
        f"{emoji.SHOPPING} Список покупок готов: {len(items)} пунктов. Смотреть: /list"
    )


@router.callback_query(F.data.startswith("plan:shoplist:"))
async def on_build_shoplist(cb: CallbackQuery, family: Family,
                            db_session: AsyncSession) -> None:
    """Сборка списка по кнопке после утверждения (и ретрай при ошибке).

    Только активное меню своей семьи.
    """
    menu_id = int(cb.data.split(":")[-1])
    menu = await repositories.get_menu_with_meals(db_session, menu_id)
    if menu is None or menu.family_id != family.id or menu.status != MenuStatus.active:
        await cb.answer("Меню не найдено или не утверждено", show_alert=True)
        return
    if await shopping_list.has_list_for_menu(db_session, menu_id=menu.id):
        await cb.answer("Список по этому меню уже составлен — смотрите /list", show_alert=True)
        return
    await cb.answer()
    await _build_shopping(cb.message, family, db_session, menu)


@router.callback_query(F.data == "plan:remind")
async def on_plan_reminder(cb: CallbackQuery, state: FSMContext, db_session: AsyncSession) -> None:
    """Кнопка из напоминания «меню заканчивается» — запускает флоу /plan."""
    await _start_plan_flow(cb.message, state, db_session)
    await cb.answer()


@router.callback_query(F.data.startswith("plan:"))
async def on_stale_callback(cb: CallbackQuery) -> None:
    """Catch-all: кнопки старых сообщений (рестарт, state.clear())."""
    await cb.answer("Сессия планирования устарела — начните заново: /plan", show_alert=True)
