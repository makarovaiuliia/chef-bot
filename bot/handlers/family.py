"""Инвайты, join по deep-link и /family (управление участниками)."""
import html

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from bot.filters import HasFamily, IsAdmin
from bot.keyboards import BTN_FAMILY, kb_main
from core import emoji
from core.exceptions import (
    AlreadyInFamily,
    CannotRemoveAdmin,
    InvalidInviteCode,
    LastAdminCannotLeave,
    MemberNotInFamily,
)
from core.repositories import get_family_members
from core.services.family_service import (
    get_admins,
    grant_admin,
    is_admin,
    join_by_invite,
    leave_family,
    regenerate_invite,
    remove_member,
)

router = Router()

INVITE_PREFIX = "inv_"


def _name(display_name: str | None, telegram_user_id: int) -> str:
    """HTML-safe member label: display_name may contain <, >, & from Telegram."""
    return html.escape(display_name) if display_name else str(telegram_user_id)


def _admin_names(admins) -> str:
    return ", ".join(_name(a.display_name, a.telegram_user_id) for a in admins) or "администратор"


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
        "Список покупок: /list, меню: /menu",
        reply_markup=kb_main(),
    )
    admins = await get_admins(db_session, family_id=joined_family.id)
    member_name = _name(member.display_name, member.telegram_user_id)
    for admin in admins:
        if admin.telegram_user_id == member.telegram_user_id:
            continue
        try:
            await message.bot.send_message(
                admin.telegram_user_id,
                f"{emoji.FAMILY} {member_name} присоединился к семье",
            )
        except Exception:
            logger.warning(
                "family: join notification failed admin_id={}", admin.telegram_user_id
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
    name = _admin_names(await get_admins(db_session, family_id=family.id))
    await message.answer(f"Приглашать может только администратор ({name}).")


def _family_name(family) -> str:
    return html.escape(family.name) if family.name else "Семья"


def _family_text(family, members) -> str:
    lines = [
        f"{emoji.CROWN + ' ' if is_admin(m) else ''}"
        f"{_name(m.display_name, m.telegram_user_id)}"
        for m in members
    ]
    return "Семья «{}»:\n{}".format(_family_name(family), "\n".join(lines))


def _kb_family(members):
    b = InlineKeyboardBuilder()
    for m in members:
        if is_admin(m):
            continue
        b.button(
            text=f"{emoji.CROWN} сделать админом: {m.display_name or m.telegram_user_id}",
            callback_data=f"fam:admin:{m.id}",
        )
    # Удалять можно только обычных участников: удаление админа было бы снятием
    # админки через черный ход (спека §4), а себя админ убирает через выход.
    for m in members:
        if is_admin(m):
            continue
        b.button(
            text=f"{emoji.REMOVE} удалить: {m.display_name or m.telegram_user_id}",
            callback_data=f"fam:rm:{m.id}",
        )
    b.button(text=f"{emoji.REFRESH} Новая инвайт-ссылка", callback_data="fam:reinvite")
    b.button(text=f"{emoji.LEAVE} Покинуть семью", callback_data="fam:leave")
    b.adjust(1)
    return b.as_markup()


def _kb_leave_only():
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.LEAVE} Покинуть семью", callback_data="fam:leave")
    return b.as_markup()


def _kb_confirm(yes_data: str, no_data: str):
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.DONE} Да", callback_data=yes_data)
    b.button(text=f"{emoji.CANCEL} Отмена", callback_data=no_data)
    b.adjust(2)
    return b.as_markup()


@router.message(Command("family"), HasFamily(), IsAdmin())
@router.message(F.text == BTN_FAMILY, HasFamily(), IsAdmin())
async def cmd_family(message: Message, db_session, family) -> None:
    members = await get_family_members(db_session, family_id=family.id)
    await message.answer(
        _family_text(family, members), reply_markup=_kb_family(members)
    )


@router.message(Command("family"), HasFamily())
@router.message(F.text == BTN_FAMILY, HasFamily())
async def cmd_family_member_view(message: Message, db_session, family) -> None:
    members = await get_family_members(db_session, family_id=family.id)
    await message.answer(_family_text(family, members), reply_markup=_kb_leave_only())


@router.callback_query(F.data.startswith("fam:admin:"), IsAdmin())
async def on_grant_admin(cb: CallbackQuery, db_session, family) -> None:
    member_id = int(cb.data.split(":")[-1])
    try:
        member = await grant_admin(db_session, family_id=family.id, member_id=member_id)
    except MemberNotInFamily:
        await cb.answer("Участник не найден", show_alert=True)
        return
    name = _name(member.display_name, member.telegram_user_id)
    await cb.message.edit_text(
        f"{emoji.CROWN} {name} теперь администратор. /family — актуальный состав."
    )
    await cb.answer()


async def _refresh_family_view(cb: CallbackQuery, db_session, family) -> None:
    """Вернуть сообщение к актуальному составу семьи (после отмены/действия)."""
    members = await get_family_members(db_session, family_id=family.id)
    await cb.message.edit_text(
        _family_text(family, members), reply_markup=_kb_family(members)
    )


@router.callback_query(F.data.startswith("fam:rm:"), IsAdmin())
async def on_remove_ask(cb: CallbackQuery, db_session, family) -> None:
    member_id = int(cb.data.split(":")[-1])
    members = await get_family_members(db_session, family_id=family.id)
    target = next((m for m in members if m.id == member_id), None)
    if target is None or is_admin(target):
        await cb.answer("Участник не найден или это администратор", show_alert=True)
        return
    # member_id едет в callback_data, а не во FSM: подтверждение переживает рестарт.
    await cb.message.edit_text(
        f"Удалить {_name(target.display_name, target.telegram_user_id)} из семьи?\n"
        "Участник потеряет доступ к меню и спискам покупок.",
        reply_markup=_kb_confirm(f"fam:rmyes:{member_id}", "fam:rmno"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("fam:rmyes:"), IsAdmin())
async def on_remove_confirm(
    cb: CallbackQuery, db_session, family, family_member
) -> None:
    member_id = int(cb.data.split(":")[-1])
    try:
        removed = await remove_member(
            db_session, family_id=family.id, actor=family_member, member_id=member_id
        )
    except MemberNotInFamily:
        await cb.answer("Участник не найден", show_alert=True)
        return
    except CannotRemoveAdmin:
        await cb.answer(
            "Администратора удалить нельзя. Себя — кнопкой «Покинуть семью».",
            show_alert=True,
        )
        return
    removed_name = _name(removed.display_name, removed.telegram_user_id)
    await cb.message.edit_text(
        f"{emoji.REMOVE} {removed_name} удален(а) из семьи. "
        "/family — актуальный состав."
    )
    try:
        await cb.bot.send_message(
            removed.telegram_user_id,
            f"Вас удалили из семьи «{_family_name(family)}». "
            "Чтобы пользоваться ботом со своей семьей, нажмите /start.",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception:
        logger.warning("family: removal notice failed id={}", removed.telegram_user_id)
    await cb.answer()


@router.callback_query(F.data == "fam:rmno", IsAdmin())
async def on_remove_cancel(cb: CallbackQuery, db_session, family) -> None:
    await _refresh_family_view(cb, db_session, family)
    await cb.answer()


@router.callback_query(F.data == "fam:leave", HasFamily())
async def on_leave_ask(cb: CallbackQuery, family) -> None:
    await cb.message.edit_text(
        f"Покинуть семью «{_family_name(family)}»?\n"
        "Вы потеряете доступ к меню и спискам покупок. Вернуться можно только "
        "по новой ссылке-приглашению от администратора.",
        reply_markup=_kb_confirm("fam:leaveyes", "fam:leaveno"),
    )
    await cb.answer()


@router.callback_query(F.data == "fam:leaveyes", HasFamily())
async def on_leave_confirm(
    cb: CallbackQuery, db_session, family, family_member
) -> None:
    actor_name = _name(family_member.display_name, family_member.telegram_user_id)
    try:
        await leave_family(db_session, family=family, member=family_member)
    except LastAdminCannotLeave:
        await cb.answer(
            "Вы единственный администратор. Сначала назначьте второго в /family.",
            show_alert=True,
        )
        return
    await cb.message.edit_text(
        f"{emoji.LEAVE} Вы покинули семью «{_family_name(family)}». "
        "Чтобы начать со своей семьей — /start."
    )
    await cb.message.answer(
        "Постоянные кнопки убраны.", reply_markup=ReplyKeyboardRemove()
    )
    for admin in await get_admins(db_session, family_id=family.id):
        try:
            await cb.bot.send_message(
                admin.telegram_user_id,
                f"{emoji.FAMILY} {actor_name} покинул(а) семью",
            )
        except Exception:
            logger.warning("family: leave notice failed id={}", admin.telegram_user_id)
    await cb.answer()


@router.callback_query(F.data == "fam:leaveno", HasFamily())
async def on_leave_cancel(cb: CallbackQuery, db_session, family, family_member) -> None:
    if is_admin(family_member):
        await _refresh_family_view(cb, db_session, family)
    else:
        members = await get_family_members(db_session, family_id=family.id)
        await cb.message.edit_text(
            _family_text(family, members), reply_markup=_kb_leave_only()
        )
    await cb.answer()


@router.callback_query(F.data == "fam:reinvite", IsAdmin())
async def on_reinvite(cb: CallbackQuery, db_session, family) -> None:
    await regenerate_invite(db_session, family=family)
    me = await cb.bot.get_me()
    link = f"https://t.me/{me.username}?start={INVITE_PREFIX}{family.invite_code}"
    await cb.message.answer(f"Новая ссылка-приглашение:\n{link}")
    await cb.answer("Старая ссылка больше не работает")
