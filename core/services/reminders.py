"""Open shopping-list line shown in the morning digest."""
from sqlalchemy.ext.asyncio import AsyncSession

from core import emoji, repositories


def _plural_items(n: int) -> str:
    """Russian noun agreement for 'пункт'."""
    last_two = n % 100
    last = n % 10
    if 11 <= last_two <= 14:
        return f"{n} пунктов"
    if last == 1:
        return f"{n} пункт"
    if 2 <= last <= 4:
        return f"{n} пункта"
    return f"{n} пунктов"


async def build_shopping_reminder(
    session: AsyncSession, *, family_id: int
) -> str | None:
    items = await repositories.get_open_shopping_items(session, family_id=family_id)
    if not items:
        return None
    return f"{emoji.SHOPPING} В списке покупок {_plural_items(len(items))} → /list"
