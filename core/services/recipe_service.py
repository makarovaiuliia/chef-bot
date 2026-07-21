from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Recipe
from core.exceptions import LLMInvalidResponse, MealNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.models import LLMRecipeResponse


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


async def get_recipe(
    session: AsyncSession, *, meal_id: int, profile_md: str, family_id: int
) -> Recipe:
    """Return cached recipe or generate via LLM (logs llm_usage on generation)."""
    cached = await repositories.get_recipe(session, meal_id)
    if cached is not None:
        return cached

    meal = await repositories.get_meal(session, meal_id)
    if meal is None:
        raise MealNotFound(f"Meal {meal_id} not found")

    user_msg = (
        f"Блюдо: {meal.dish_name}. "
        f"Гарниры: {', '.join(meal.side_dishes or [])}. "
        f"Дай подробный рецепт; число порций — по составу семьи из контекста."
    )
    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("recipe", profile_md=profile_md),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=2048,
    )

    try:
        data = parse_json_response(resp.text)
        validated = LLMRecipeResponse.model_validate(data)
    except Exception as e:
        raise LLMInvalidResponse(f"Could not parse recipe: {e}") from e

    recipe = await repositories.save_recipe(
        session,
        meal_id=meal_id,
        content_md=validated.content_md,
        ingredients=[i.model_dump() for i in validated.ingredients],
        prep_minutes=validated.prep_minutes,
    )
    await repositories.log_llm_usage(
        session,
        family_id=family_id,
        operation="recipe",
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
    )
    return recipe
