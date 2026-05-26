from datetime import date as DateType
from functools import lru_cache

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Menu
from core.exceptions import LLMInvalidResponse, MenuNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.models import LLMMenuResponse


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


async def start_planning(
    session: AsyncSession,
    *,
    family_id: int,
    days_count: int,
    start_date: DateType,
    fridge_text: str,
) -> Menu:
    """Generate a draft menu via Claude and persist it. Returns Menu (status=draft).

    days_count is a positive integer; the FSM wizard enforces the 7/14 user choice.
    """
    if days_count < 1:
        raise ValueError("days_count must be >= 1")

    user_msg = (
        f"Дата начала: {start_date.isoformat()}. "
        f"Дней: {days_count}. "
        f"В холодильнике: {fridge_text or 'ничего особенного'}. "
        f"Сгенерируй меню."
    )

    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("menu_planner"),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=4096,
    )
    logger.info("menu generation: in={} out={}", resp.tokens_in, resp.tokens_out)

    try:
        data = parse_json_response(resp.text)
        validated = LLMMenuResponse.model_validate(data)
    except Exception as e:
        logger.warning("first parse failed, retrying with hint: {}", e)
        retry_msg = (
            user_msg
            + "\n\nПРЕДЫДУЩИЙ ОТВЕТ НЕВАЛИДЕН. Верни СТРОГО JSON без markdown."
        )
        resp = await llm.chat(
            system_blocks=build_system_blocks("menu_planner"),
            messages=[{"role": "user", "content": retry_msg}],
            max_tokens=4096,
        )
        try:
            data = parse_json_response(resp.text)
            validated = LLMMenuResponse.model_validate(data)
        except Exception as e2:
            raise LLMInvalidResponse(f"Failed to parse menu after retry: {e2}") from e2

    meals_payload = [m.model_dump(mode="python") for m in validated.meals]
    return await repositories.create_draft_menu(
        session,
        family_id=family_id,
        start_date=start_date,
        days_count=days_count,
        meals=meals_payload,
    )


async def approve(session: AsyncSession, menu_id: int) -> None:
    menu = await repositories.get_menu_with_meals(session, menu_id)
    if menu is None:
        raise MenuNotFound(f"Menu {menu_id} not found")
    await repositories.approve_menu(session, menu_id)


async def get_active(session: AsyncSession, family_id: int) -> Menu | None:
    return await repositories.get_active_menu(session, family_id)
