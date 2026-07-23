"""Настройки семьи: утренний дайджест (вкл/выкл, час). Менять может только админ."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import HasFamily, IsAdmin
from bot.keyboards import kb_settings
from core import emoji
from core.db import Family, FamilyMember
from core.services.family_service import is_admin, update_digest_settings

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily())


def _settings_text(family: Family) -> str:
    state = "включен" if family.digest_enabled else "выключен"
    return (
        f"{emoji.PROFILE} Настройки семьи\n\n"
        f"Утренний дайджест: {state}, в {family.digest_hour}:00\n"
        f"Часовой пояс: {family.timezone} (задается городом при онбординге)"
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


@router.callback_query(F.data.startswith("set:"))
async def on_set_denied(cb: CallbackQuery) -> None:
    await cb.answer("Настройки меняет администратор семьи", show_alert=True)
