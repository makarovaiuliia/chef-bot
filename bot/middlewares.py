from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from loguru import logger

from core.db import session_scope
from core.services.family_service import get_or_create_family, is_authorized


class AllowlistMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or not is_authorized(user.id):
            logger.warning(
                "rejected non-allowlisted user user_id={}",
                user.id if user else "?",
            )
            return None
        return await handler(event, data)


class FamilyResolverMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User = data["event_from_user"]
        async with session_scope() as session:
            family, member = await get_or_create_family(
                session,
                telegram_user_id=user.id,
                display_name=user.full_name,
            )
            data["family"] = family
            data["family_member"] = member
            data["db_session"] = session
            return await handler(event, data)
