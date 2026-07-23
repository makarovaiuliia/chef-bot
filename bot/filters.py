from typing import Any

from aiogram.filters import Filter
from aiogram.types import TelegramObject

from config import get_settings
from core.services.family_service import is_admin


class HasFamily(Filter):
    """Пропускает апдейт только если юзер уже состоит в семье."""

    async def __call__(self, event: TelegramObject, family: Any = None, **_: Any) -> bool:
        return family is not None


class IsAdmin(Filter):
    async def __call__(
        self, event: TelegramObject, family_member: Any = None, **_: Any
    ) -> bool:
        return family_member is not None and is_admin(family_member)


class IsSuperadmin(Filter):
    """Оператор продукта (config.superadmin_ids) — отдельный слой доверия, не роль семьи."""

    async def __call__(self, event: TelegramObject, **_: Any) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in get_settings().superadmin_ids
