from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import Family, FamilyMember
from core.services import conversation

router = Router()


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

    try:
        reply = await conversation.handle_message(
            db_session,
            family_id=family.id,
            telegram_user_id=family_member.telegram_user_id,
            text=message.text,
        )
    except Exception as e:
        logger.exception("conversation failure: {}", e)
        await message.answer("Не получилось ответить. Попробуй ещё раз.")
        return
    await message.answer(reply)
