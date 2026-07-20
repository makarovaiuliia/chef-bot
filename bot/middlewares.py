from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from core.db import session_scope
from core.services.family_service import resolve_member


class FamilyResolverMiddleware(BaseMiddleware):
    """Резолвит семью юзера. family/family_member могут быть None —
    доступ к рабочим командам отсекает фильтр HasFamily."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        async with session_scope() as session:
            resolved = await resolve_member(session, user.id)
            family, member = resolved if resolved else (None, None)
            data["family"] = family
            data["family_member"] = member
            data["db_session"] = session
            return await handler(event, data)
