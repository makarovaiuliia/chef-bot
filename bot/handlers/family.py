"""Инвайты, join по deep-link и /family (управление участниками)."""
import html

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from bot.filters import HasFamily, IsAdmin
from core import emoji
from core.exceptions import AlreadyInFamily, InvalidInviteCode, MemberNotInFamily
from core.repositories import get_family_members
from core.services.family_service import (
    get_admin,
    is_admin,
    join_by_invite,
    regenerate_invite,
    set_can_plan,
    transfer_admin,
)

router = Router()

INVITE_PREFIX = "inv_"


def _name(display_name: str | None, telegram_user_id: int) -> str:
    """HTML-safe member label: display_name may contain <, >, & from Telegram."""
    return html.escape(display_name) if display_name else str(telegram_user_id)


@router.message(CommandStart(deep_link=True, magic=F.args.startswith(INVITE_PREFIX)))
async def start_with_invite(
    message: Message, command: CommandObject, db_session, state: FSMContext, family=None
) -> None:
    # Юзер мог кликнуть инвайт посреди онбординга — сбрасываем его FSM-state.
    await state.clear()
    if family is not None:
        await message.answer("Вы уже состоите в семье.")
        return
    code = command.args.removeprefix(INVITE_PREFIX)
    try:
        joined_family, member = await join_by_invite(
            db_session,
            invite_code=code,
            telegram_user_id=message.from_user.id,
            display_name=message.from_user.full_name,
        )
    except InvalidInviteCode:
        await message.answer("Ссылка-приглашение недействительна. Попросите новую.")
        return
    except AlreadyInFamily:
        await message.answer("Вы уже состоите в семье.")
        return
    family_name = html.escape(joined_family.name) if joined_family.name else "Семья"
    await message.answer(
        f"{emoji.DONE} Вы присоединились к семье «{family_name}»!\n"
        "Список покупок: /list, меню: /menu"
    )
    admin = await get_admin(db_session, family_id=joined_family.id)
    if admin and admin.telegram_user_id != member.telegram_user_id:
        member_name = _name(member.display_name, member.telegram_user_id)
        try:
            await message.bot.send_message(
                admin.telegram_user_id,
                f"{emoji.FAMILY} {member_name} присоединился к семье",
            )
        except Exception:
            logger.warning(
                "family: join notification failed admin_id={}",
                admin.telegram_user_id,
            )


@router.message(Command("invite"), HasFamily(), IsAdmin())
async def cmd_invite(message: Message, family) -> None:
    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}?start={INVITE_PREFIX}{family.invite_code}"
    await message.answer(
        f"Ссылка-приглашение в семью (перешлите близким):\n{link}"
    )


@router.message(Command("invite"), HasFamily())
async def cmd_invite_denied(message: Message, db_session, family) -> None:
    admin = await get_admin(db_session, family_id=family.id)
    name = html.escape(admin.display_name) if admin and admin.display_name else "администратор"
    await message.answer(f"Приглашать может только администратор ({name}).")


def _kb_family(members, admin_id: int):
    b = InlineKeyboardBuilder()
    for m in members:
        if m.id == admin_id:
            continue
        mark = emoji.DONE if m.can_plan else emoji.UNCHECKED
        b.button(
            text=f"{mark} план: {m.display_name or m.telegram_user_id}",
            callback_data=f"fam:plan:{m.id}",
        )
        b.button(
            text=f"{emoji.CROWN} сделать админом: {m.display_name or m.telegram_user_id}",
            callback_data=f"fam:admin:{m.id}",
        )
    b.button(text=f"{emoji.REFRESH} Новая инвайт-ссылка", callback_data="fam:reinvite")
    b.adjust(1)
    return b.as_markup()


@router.message(Command("family"), HasFamily(), IsAdmin())
async def cmd_family(message: Message, db_session, family, family_member) -> None:
    members = await get_family_members(db_session, family_id=family.id)
    lines = [
        f"{emoji.CROWN + ' ' if is_admin(m) else ''}"
        f"{_name(m.display_name, m.telegram_user_id)}"
        + (" — может планировать" if m.can_plan and not is_admin(m) else "")
        for m in members
    ]
    family_name = html.escape(family.name) if family.name else "Семья"
    await message.answer(
        "Семья «{}»:\n{}".format(family_name, "\n".join(lines)),
        reply_markup=_kb_family(members, admin_id=family_member.id),
    )


@router.message(Command("family"), HasFamily())
async def cmd_family_member_view(message: Message, db_session, family) -> None:
    members = await get_family_members(db_session, family_id=family.id)
    lines = [
        f"{emoji.CROWN + ' ' if is_admin(m) else ''}"
        f"{_name(m.display_name, m.telegram_user_id)}"
        for m in members
    ]
    family_name = html.escape(family.name) if family.name else "Семья"
    await message.answer("Семья «{}»:\n{}".format(family_name, "\n".join(lines)))


@router.callback_query(F.data.startswith("fam:plan:"), IsAdmin())
async def on_toggle_plan(cb: CallbackQuery, db_session, family, family_member) -> None:
    member_id = int(cb.data.split(":")[-1])
    members = await get_family_members(db_session, family_id=family.id)
    target = next((m for m in members if m.id == member_id), None)
    if target is None:
        await cb.answer("Участник не найден", show_alert=True)
        return
    updated = await set_can_plan(db_session, member_id=member_id, value=not target.can_plan)
    members = await get_family_members(db_session, family_id=family.id)
    await cb.message.edit_reply_markup(
        reply_markup=_kb_family(members, admin_id=family_member.id)
    )
    state = "может планировать" if updated.can_plan else "больше не планирует"
    await cb.answer(f"{updated.display_name or 'Участник'} {state}")


@router.callback_query(F.data.startswith("fam:admin:"), IsAdmin())
async def on_transfer_admin(cb: CallbackQuery, db_session, family) -> None:
    member_id = int(cb.data.split(":")[-1])
    try:
        await transfer_admin(db_session, family_id=family.id, to_member_id=member_id)
    except MemberNotInFamily:
        await cb.answer("Участник не найден", show_alert=True)
        return
    await cb.message.edit_text("Права администратора переданы. /family — актуальный состав.")
    await cb.answer()


@router.callback_query(F.data == "fam:reinvite", IsAdmin())
async def on_reinvite(cb: CallbackQuery, db_session, family) -> None:
    await regenerate_invite(db_session, family=family)
    me = await cb.bot.get_me()
    link = f"https://t.me/{me.username}?start={INVITE_PREFIX}{family.invite_code}"
    await cb.message.answer(f"Новая ссылка-приглашение:\n{link}")
    await cb.answer("Старая ссылка больше не работает")
