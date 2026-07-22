import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.filters import HasFamily, IsAdmin
from bot.formatting import md_to_telegram_html
from bot.fsm import ProfileEdit
from bot.keyboards import BTN_ADD, BTN_FAMILY, BTN_TODAY
from core import emoji
from core.services.family_service import get_admins, is_admin, update_profile

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily())


def _kb_edit():
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.EDIT} Редактировать", callback_data="profile:edit")
    return b.as_markup()


@router.message(Command("profile"))
async def cmd_profile(message: Message, family, family_member) -> None:
    profile_text = (
        md_to_telegram_html(family.profile_md) if family.profile_md else "(профиль пуст)"
    )
    text = f"Профиль семьи:\n\n{profile_text}"
    if is_admin(family_member):
        await message.answer(text, reply_markup=_kb_edit())
    else:
        await message.answer(text)


@router.callback_query(F.data == "profile:edit", IsAdmin())
async def on_edit(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileEdit.waiting_text)
    await cb.message.answer(
        "Пришлите новую версию профиля целиком:", reply_markup=ForceReply()
    )
    await cb.answer()


@router.callback_query(F.data == "profile:edit")
async def on_edit_denied(cb: CallbackQuery, db_session, family) -> None:
    admins = await get_admins(db_session, family_id=family.id)
    names = ", ".join(
        html.escape(a.display_name) if a.display_name else str(a.telegram_user_id)
        for a in admins
    ) or "администратор"
    await cb.answer(f"Профиль может менять только {names}", show_alert=True)


@router.message(
    ProfileEdit.waiting_text,
    F.text,
    ~F.text.in_({BTN_ADD, BTN_TODAY, BTN_FAMILY}),
    ~F.text.startswith("/"),
    IsAdmin(),
)
async def on_new_text(message: Message, state: FSMContext, db_session, family) -> None:
    await update_profile(db_session, family=family, profile_md=message.text)
    await state.clear()
    await message.answer(f"{emoji.DONE} Профиль обновлен.")
