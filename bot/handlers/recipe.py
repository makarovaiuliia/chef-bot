from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import Family
from core.exceptions import LLMError
from core.services import recipe_service

router = Router()


@router.message(Command("recipe"))
async def cmd_recipe(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    meal_id = await recipe_service.get_current_meal(db_session, family_id=family.id)
    if meal_id is None:
        await message.answer(
            "На сегодня в активном меню нет блюда для текущего времени. "
            "Пришли JSON-файл с меню."
        )
        return
    await message.answer("Готовлю рецепт...")
    try:
        recipe = await recipe_service.get_recipe(db_session, meal_id=meal_id)
    except LLMError as e:
        logger.exception("recipe error: {}", e)
        await message.answer("Не удалось сгенерировать рецепт. Попробуй позже.")
        return
    await message.answer(recipe.content_md)
