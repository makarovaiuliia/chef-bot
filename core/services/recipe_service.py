from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core import repositories
from core.db import MealSlot, Recipe
from core.exceptions import LLMInvalidResponse, MealNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.models import LLMRecipeResponse


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


async def get_recipe(session: AsyncSession, *, meal_id: int) -> Recipe:
    """Return cached recipe or generate via LLM."""
    cached = await repositories.get_recipe(session, meal_id)
    if cached is not None:
        return cached

    meal = await repositories.get_meal(session, meal_id)
    if meal is None:
        raise MealNotFound(f"Meal {meal_id} not found")

    user_msg = (
        f"Блюдо: {meal.dish_name}. "
        f"Гарниры: {', '.join(meal.side_dishes or [])}. "
        f"Дай мне подробный рецепт на 2 порции."
    )
    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("recipe"),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=2048,
    )
    logger.info("recipe gen: in={} out={}", resp.tokens_in, resp.tokens_out)

    try:
        data = parse_json_response(resp.text)
        validated = LLMRecipeResponse.model_validate(data)
    except Exception as e:
        raise LLMInvalidResponse(f"Could not parse recipe: {e}") from e

    return await repositories.save_recipe(
        session,
        meal_id=meal_id,
        content_md=validated.content_md,
        ingredients=[i.model_dump() for i in validated.ingredients],
        prep_minutes=validated.prep_minutes,
    )


async def get_current_meal(
    session: AsyncSession, *, family_id: int
) -> int | None:
    """Pick today's lunch before 16:00 local time, dinner after."""
    tz = ZoneInfo(get_settings().timezone)
    now = datetime.now(tz)
    today = now.date()
    target_slot = MealSlot.lunch if now.hour < 16 else MealSlot.dinner

    meals = await repositories.get_meals_for_date(session, family_id, today)
    for m in meals:
        if m.slot == target_slot:
            return m.id
    return None
