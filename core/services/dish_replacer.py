from functools import lru_cache

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Meal, ProteinKind
from core.exceptions import LLMInvalidResponse, MealNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.services import limits


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


class ReplacementOption(BaseModel):
    dish_name: str
    side_dishes: list[str] = Field(default_factory=list)
    protein_kind: ProteinKind


class _AlternativesSchema(BaseModel):
    alternatives: list[ReplacementOption] = Field(min_length=2, max_length=3)


async def suggest_replacements(
    session: AsyncSession,
    *,
    meal_id: int,
    hint: str | None,
    profile_md: str,
    family_id: int,
) -> list[ReplacementOption]:
    """2-3 варианта замены. Ничего не применяет; логирует usage при успехе."""
    meal = await repositories.get_meal(session, meal_id)
    if meal is None:
        raise MealNotFound(f"Meal {meal_id} not found")
    await limits.ensure_within_limits(session, family_id=family_id, operation="replace")

    user_msg = (
        f"Текущее блюдо: {meal.dish_name} "
        f"(гарниры: {', '.join(meal.side_dishes or [])}, белок: {meal.protein_kind.value}). "
        f"Дата: {meal.date.isoformat()}, прием: {meal.slot.value}. "
        f"Пожелание пользователя: {hint or 'просто другое блюдо'}. "
        f"Предложи 2-3 варианта замены."
    )
    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("dish_replacer", profile_md=profile_md),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=1024,
    )
    try:
        data = parse_json_response(resp.text)
        parsed = _AlternativesSchema.model_validate(data)
    except Exception as e:
        raise LLMInvalidResponse(f"Failed to parse replacement options: {e}") from e

    await repositories.log_llm_usage(
        session,
        family_id=family_id,
        operation="replace",
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
    )
    return parsed.alternatives


async def apply_replacement(
    session: AsyncSession, *, meal_id: int, option: ReplacementOption
) -> Meal:
    return await repositories.update_meal(
        session,
        meal_id=meal_id,
        dish_name=option.dish_name,
        side_dishes=option.side_dishes,
        protein_kind=option.protein_kind,
    )


async def replace_meal(
    session: AsyncSession, *, meal_id: int, hint: str | None, profile_md: str, family_id: int
) -> Meal:
    """Однократная замена (для tool-use агента): первый предложенный вариант."""
    options = await suggest_replacements(
        session, meal_id=meal_id, hint=hint, profile_md=profile_md, family_id=family_id
    )
    return await apply_replacement(session, meal_id=meal_id, option=options[0])
