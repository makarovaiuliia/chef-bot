from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.filters import HasFamily, IsAdmin
from bot.formatting import md_to_telegram_html
from bot.fsm import ProfileEdit
from core import emoji
from core.services.family_service import get_admin, is_admin, update_profile

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
    admin = await get_admin(db_session, family_id=family.id)
    name = admin.display_name if admin else "администратор"
    await cb.answer(f"Профиль может менять только {name}", show_alert=True)


@router.message(ProfileEdit.waiting_text, F.text, IsAdmin())
async def on_new_text(message: Message, state: FSMContext, db_session, family) -> None:
    await update_profile(db_session, family=family, profile_md=message.text)
    await state.clear()
    await message.answer(f"{emoji.DONE} Профиль обновлён.")
