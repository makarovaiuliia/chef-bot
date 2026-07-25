from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import HasFamily
from bot.formatting import md_to_telegram_html, wait_text
from bot.handlers.start import help_text
from config import get_settings
from core import emoji
from core.db import Family, FamilyMember
from core.services import conversation

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily())


def _conversation_enabled() -> bool:
    return get_settings().conversation_enabled


@router.message(F.text & ~F.text.startswith("/"))
async def handle_free_text(
    message: Message,
    state: FSMContext,
    family: Family,
    family_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    if await state.get_state() is not None:
        return

    if not _conversation_enabled():
        await message.answer(
            "Я понимаю команды, а не свободный текст. Вот что я умею:\n\n" + help_text()
        )
        return

    thinking = await message.answer(wait_text(emoji.WAIT, "Думаю", "conversation"))
    try:
        reply = await conversation.handle_message(
            db_session,
            family_id=family.id,
            telegram_user_id=family_member.telegram_user_id,
            text=message.text,
            profile_md=family.profile_md or "",
        )
    except Exception as e:
        logger.exception("conversation failure: {}", e)
        await thinking.edit_text("Не получилось ответить. Попробуй еще раз.")
        return
    await thinking.edit_text(md_to_telegram_html(reply))
