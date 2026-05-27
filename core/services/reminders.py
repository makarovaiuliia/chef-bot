"""Daily shopping reminder."""
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories


def _plural_items(n: int) -> str:
    """Russian noun agreement for 'незакрытый пункт'."""
    last_two = n % 100
    last = n % 10
    if 11 <= last_two <= 14:
        return f"{n} незакрытых пунктов"
    if last == 1:
        return f"{n} незакрытый пункт"
    if 2 <= last <= 4:
        return f"{n} незакрытых пункта"
    return f"{n} незакрытых пунктов"


async def build_shopping_reminder(
    session: AsyncSession, *, family_id: int
) -> str | None:
    items = await repositories.get_open_shopping_items(session, family_id=family_id)
    if not items:
        return None
    return f"🛒 В списке покупок ещё {_plural_items(len(items))}. /list"
