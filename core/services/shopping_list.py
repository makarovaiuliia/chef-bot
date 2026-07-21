from functools import lru_cache

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import emoji, repositories
from core.db import FamilyMember, Menu, ShoppingItem, ShoppingList
from core.exceptions import LLMInvalidResponse
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.meal_format import format_dish_with_sides, slot_label


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


class _ItemSchema(BaseModel):
    name: str
    quantity: str = ""


class _ShoppingSchema(BaseModel):
    items: list[_ItemSchema] = Field(min_length=1)


def build_added_notifications(
    adder: FamilyMember,
    members: list[FamilyMember],
    names: list[str],
) -> list[tuple[int, str]]:
    """(telegram_id, text) для всех членов семьи, кроме добавившего."""
    if not names:
        return []
    who = adder.display_name or "Кто-то"
    text = f"{emoji.SHOPPING} {who} добавил в список: {', '.join(names)}"
    return [
        (m.telegram_user_id, text)
        for m in members
        if m.telegram_user_id != adder.telegram_user_id
    ]


async def get_open_items(
    session: AsyncSession, *, family_id: int
) -> list[ShoppingItem]:
    return await repositories.get_open_shopping_items(session, family_id=family_id)


async def toggle_bought(
    session: AsyncSession, *, item_id: int, family_id: int
) -> ShoppingItem | None:
    item = await repositories.get_shopping_item(session, item_id, family_id=family_id)
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
    store: str | None = None,
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


async def close_stale_menu_items(session: AsyncSession, *, family_id: int) -> int:
    """Закрыть открытые пункты прошлых меню. Ручные пункты (/add) не трогаем."""
    stmt = select(ShoppingItem).where(
        ShoppingItem.family_id == family_id,
        ShoppingItem.bought.is_(False),
        ShoppingItem.shopping_list_id.is_not(None),
    )
    items = list((await session.execute(stmt)).scalars().all())
    for item in items:
        await repositories.mark_shopping_item_bought(session, item.id, bought=True)
    return len(items)


def _menu_as_text(menu: Menu) -> str:
    lines = []
    for m in sorted(menu.meals, key=lambda m: (m.date, m.slot.value)):
        lines.append(
            f"{m.date.isoformat()} · {slot_label(m.slot)}: "
            f"{format_dish_with_sides(m.dish_name, m.side_dishes)}"
        )
    return "\n".join(lines)


async def build_from_menu(
    session: AsyncSession,
    *,
    family_id: int,
    menu: Menu,
    profile_md: str,
    llm: LLMClient | None = None,
) -> list[ShoppingItem]:
    """LLM-сборка списка покупок по блюдам меню (operation="shopping")."""
    llm = llm or get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("shopping_list_builder", profile_md=profile_md),
        messages=[{"role": "user", "content": f"Меню:\n{_menu_as_text(menu)}"}],
        max_tokens=2048,
    )
    try:
        parsed = _ShoppingSchema.model_validate(parse_json_response(resp.text))
    except Exception as e:
        raise LLMInvalidResponse(f"Failed to parse shopping list: {e}") from e

    await close_stale_menu_items(session, family_id=family_id)
    sl = ShoppingList(menu_id=menu.id)
    session.add(sl)
    await session.flush()
    items = [
        ShoppingItem(
            shopping_list_id=sl.id, family_id=family_id, name=i.name, quantity=i.quantity
        )
        for i in parsed.items
    ]
    session.add_all(items)
    await session.flush()
    await repositories.log_llm_usage(
        session,
        family_id=family_id,
        operation="shopping",
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
    )
    return items
