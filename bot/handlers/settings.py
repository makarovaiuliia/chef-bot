"""Настройки семьи: утренний дайджест (вкл/выкл, час). Менять может только админ."""
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import HasFamily, IsAdmin
from bot.formatting import wait_text
from bot.fsm import SettingsFlow
from bot.keyboards import MAIN_BUTTONS, kb_main, kb_settings, kb_want_subscription
from core import emoji
from core.db import Family, FamilyMember
from core.exceptions import LimitExceeded, LLMError
from core.services import subscription
from core.services.family_service import (
    change_family_timezone,
    is_admin,
    update_digest_settings,
)
from core.services.limits import denial_text, subscription_active

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily())


def _settings_text(family: Family) -> str:
    state = "включен" if family.digest_enabled else "выключен"
    today = datetime.now(ZoneInfo(family.timezone or "UTC")).date()
    return (
        f"{emoji.PROFILE} Настройки семьи\n\n"
        f"Утренний дайджест: {state}, в {family.digest_hour}:00\n"
        f"Часовой пояс: {family.timezone}\n"
        f"{subscription.status_line(family, today)}"
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, family: Family, family_member: FamilyMember) -> None:
    if is_admin(family_member):
        await message.answer(_settings_text(family), reply_markup=kb_settings(family))
    else:
        await message.answer(_settings_text(family))


@router.callback_query(F.data.startswith("set:digest:"), IsAdmin())
async def on_toggle_digest(cb: CallbackQuery, family: Family, db_session: AsyncSession) -> None:
    suffix = cb.data.split(":")[-1]
    if suffix not in {"on", "off"}:
        await cb.answer("Недоступное значение", show_alert=True)
        return
    enabled = suffix == "on"
    if enabled == family.digest_enabled:
        await cb.answer()
        return
    await update_digest_settings(db_session, family=family, enabled=enabled)
    await cb.message.edit_text(_settings_text(family), reply_markup=kb_settings(family))
    await cb.answer("Дайджест включен" if enabled else "Дайджест выключен")


@router.callback_query(F.data.startswith("set:hour:"), IsAdmin())
async def on_set_hour(cb: CallbackQuery, family: Family, db_session: AsyncSession) -> None:
    try:
        hour = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer("Недоступный час", show_alert=True)
        return
    if hour == family.digest_hour:
        await cb.answer("Уже установлено")
        return
    try:
        await update_digest_settings(db_session, family=family, hour=hour)
    except ValueError:
        await cb.answer("Недоступный час", show_alert=True)
        return
    await cb.message.edit_text(_settings_text(family), reply_markup=kb_settings(family))
    await cb.answer(f"Дайджест в {hour}:00")


@router.callback_query(F.data == "set:tz", IsAdmin())
async def on_tz_button(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.tz_city)
    await cb.message.answer(
        "Напишите ваш город (например: Москва, Дубай):", reply_markup=ForceReply()
    )
    await cb.answer()


@router.message(
    SettingsFlow.tz_city,
    F.text,
    ~F.text.in_(MAIN_BUTTONS),
    ~F.text.startswith("/"),
    IsAdmin(),
)
async def on_tz_city(
    message: Message, state: FSMContext, family: Family, db_session: AsyncSession
) -> None:
    # kb_main на плейсхолдере возвращает постоянную клавиатуру, вытесненную
    # ForceReply города (паттерн 3613a1f); дальше правим само сообщение.
    placeholder = await message.answer(
        wait_text(emoji.TIMEZONE, "Определяю таймзону", "tz_detect"),
        reply_markup=kb_main(),
    )
    try:
        tz = await change_family_timezone(db_session, family=family, city=message.text)
    except LimitExceeded as e:
        await state.clear()
        await placeholder.edit_text(
            denial_text(e),
            reply_markup=None if subscription_active(family) else kb_want_subscription(),
        )
        return
    except LLMError:
        logger.exception("settings: tz detect failed family_id={}", family.id)
        await state.clear()
        await placeholder.edit_text(
            "Не получилось определить таймзону. Попробуйте позже: /settings"
        )
        return
    if tz is None:
        await placeholder.edit_text("Не узнал город, попробуйте иначе:")
        await message.answer(
            "Например: Москва, Дубай",
            reply_markup=ForceReply(input_field_placeholder="ваш город"),
        )
        return
    await state.clear()
    now_local = datetime.now(ZoneInfo(tz)).strftime("%H:%M")
    await placeholder.edit_text(
        f"{emoji.DONE} Таймзона обновлена: {tz} (у вас сейчас {now_local})"
    )


@router.message(SettingsFlow.tz_city, ~F.text, IsAdmin())
async def on_tz_city_not_text(message: Message) -> None:
    await message.answer("Не узнал город, попробуйте текстом (например: Москва, Дубай).")


@router.callback_query(F.data.startswith("set:"))
async def on_set_denied(cb: CallbackQuery) -> None:
    await cb.answer("Настройки меняет администратор семьи", show_alert=True)
