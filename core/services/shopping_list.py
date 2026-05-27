from functools import lru_cache

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import ShoppingItem, ShoppingList, Store
from core.exceptions import LLMInvalidResponse, MenuNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.models import LLMShoppingResponse


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


async def build_from_menu(
    session: AsyncSession, *, menu_id: int, family_id: int
) -> ShoppingList:
    menu = await repositories.get_menu_with_meals(session, menu_id)
    if menu is None:
        raise MenuNotFound(f"Menu {menu_id} not found")

    meals_summary = "\n".join(
        f"- {m.date.isoformat()} {m.slot.value}: {m.dish_name} "
        f"(гарниры: {', '.join(m.side_dishes or [])})"
        for m in menu.meals
    )
    user_msg = (
        f"Меню на {menu.days_count} дней:\n{meals_summary}\n\n"
        f"Сгенерируй список покупок (на 2 порции каждого блюда). "
        f"Исключи продукты из кладовки."
    )

    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("shopping_list"),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=2048,
    )
    logger.info("shopping list: in={} out={}", resp.tokens_in, resp.tokens_out)

    try:
        data = parse_json_response(resp.text)
        validated = LLMShoppingResponse.model_validate(data)
    except Exception as e:
        raise LLMInvalidResponse(f"Could not parse shopping list: {e}") from e

    items_payload = [i.model_dump() for i in validated.items]
    return await repositories.create_shopping_list(
        session, menu_id=menu_id, family_id=family_id, items=items_payload
    )


async def get_open_items(
    session: AsyncSession, *, family_id: int
) -> list[ShoppingItem]:
    return await repositories.get_open_shopping_items(session, family_id=family_id)


async def toggle_bought(
    session: AsyncSession, *, item_id: int
) -> ShoppingItem | None:
    item = await repositories.get_shopping_item(session, item_id)
    if item is None:
        return None
    return await repositories.mark_shopping_item_bought(
        session, item_id, bought=not item.bought
    )


async def add_manual_item(
    session: AsyncSession,
    *,
    family_id: int,
    name: str,
    quantity: str = "",
    store: Store = Store.other,
) -> ShoppingItem:
    """Add a standalone shopping item (not bound to any menu's shopping_list)."""
    item = ShoppingItem(
        shopping_list_id=None,
        family_id=family_id,
        name=name,
        quantity=quantity,
        store=store,
    )
    session.add(item)
    await session.flush()
    return item
