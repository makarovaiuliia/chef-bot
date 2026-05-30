from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import FamilyMember, ShoppingItem, Store


def build_add_notifications(
    *,
    adder_id: int,
    vova_id: int | None,
    members: list[FamilyMember],
    names: list[str],
) -> list[tuple[int, str]]:
    """When Вова adds items, build (telegram_id, text) pairs for every other member.

    Returns [] unless the adder is Вова and there is something to announce.
    """
    if vova_id is None or adder_id != vova_id or not names:
        return []
    text = f"🛒 Вова добавил в список: {', '.join(names)}"
    return [
        (m.telegram_user_id, text)
        for m in members
        if m.telegram_user_id != vova_id
    ]


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
