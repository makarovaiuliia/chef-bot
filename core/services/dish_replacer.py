from functools import lru_cache

from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Meal, ProteinKind
from core.exceptions import LLMInvalidResponse, MealNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


class _ReplacementSchema(BaseModel):
    dish_name: str
    side_dishes: list[str]
    protein_kind: ProteinKind


async def replace_meal(
    session: AsyncSession, *, meal_id: int, hint: str | None
) -> Meal:
    meal = await repositories.get_meal(session, meal_id)
    if meal is None:
        raise MealNotFound(f"Meal {meal_id} not found")

    user_msg = (
        f"Текущее блюдо: {meal.dish_name} "
        f"(гарниры: {', '.join(meal.side_dishes or [])}, белок: {meal.protein_kind.value}). "
        f"Дата: {meal.date.isoformat()}, приём: {meal.slot.value}. "
        f"Пожелание пользователя: {hint or 'просто другое блюдо'}. "
        f"Предложи замену."
    )

    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("dish_replacer"),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=512,
    )
    logger.info("dish replace: in={} out={}", resp.tokens_in, resp.tokens_out)

    try:
        data = parse_json_response(resp.text)
        new = _ReplacementSchema.model_validate(data)
    except Exception as e:
        raise LLMInvalidResponse(f"Failed to parse replacement: {e}") from e

    return await repositories.update_meal(
        session,
        meal_id=meal_id,
        dish_name=new.dish_name,
        side_dishes=new.side_dishes,
        protein_kind=new.protein_kind,
    )
