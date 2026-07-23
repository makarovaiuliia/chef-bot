"""Заявки «хочу подписку» с заглушек лимитов (роадмап: проверка спроса до биллинга)."""
import html

from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import HasFamily
from config import get_settings
from core.db import Family
from core.repositories import add_subscription_request

router = Router()
router.callback_query.filter(HasFamily())


@router.callback_query(F.data == "sub:want")
async def on_want_subscription(
    cb: CallbackQuery, family: Family, db_session: AsyncSession
) -> None:
    created = await add_subscription_request(
        db_session, family_id=family.id, telegram_user_id=cb.from_user.id
    )
    if not created:
        await cb.answer("Вы уже в списке — напишем, как только подписка появится!")
        return
    await cb.answer("Записали! Напишем, как только подписку можно будет оформить.")
    family_name = html.escape(family.name) if family.name else str(family.id)
    for admin_id in get_settings().superadmin_ids:
        try:
            await cb.bot.send_message(
                admin_id,
                f"Заявка на подписку: семья «{family_name}» (id={family.id}), "
                f"от юзера {cb.from_user.id}",
            )
        except Exception:
            logger.warning("subscription: superadmin notify failed id={}", admin_id)
