"""Триал-лимиты и месячный токен-потолок (спека §6).

Вызывается сервисами ПЕРЕД каждым LLM-вызовом. Триал — разовый (пожизненный)
лимит по числу операций; потолок — сумма токенов за календарный месяц (UTC).
Генерация профиля в онбординге сюда не ходит (вне лимитов, семьи еще нет).
"""
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core import repositories
from core.exceptions import MonthlyCapExceeded, TrialLimitExceeded


def _trial_limits() -> dict[str, int]:
    s = get_settings()
    return {
        "menu_gen": s.trial_menu_gen_limit,
        "replace": s.trial_replace_limit,
        "recipe": s.trial_recipe_limit,
        "shopping": s.trial_shopping_limit,
    }


async def ensure_within_limits(
    session: AsyncSession, *, family_id: int, operation: str, now: datetime | None = None
) -> None:
    limit = _trial_limits().get(operation)
    if limit is not None:
        used = await repositories.count_llm_operations(
            session, family_id=family_id, operation=operation
        )
        if used >= limit:
            raise TrialLimitExceeded(operation)
    now = now or datetime.now(UTC)
    tokens = await repositories.sum_llm_tokens_current_month(
        session, family_id=family_id, now=now
    )
    if tokens >= get_settings().monthly_token_cap_per_family:
        raise MonthlyCapExceeded


_OPERATION_LABELS = {
    "menu_gen": "генераций меню",
    "replace": "замен блюд",
    "recipe": "рецептов",
    "shopping": "списков покупок",
}


def denial_text(exc: Exception) -> str:
    """Вежливый отказ (спека §6): подписка скоро / потолок с датой сброса."""
    if isinstance(exc, TrialLimitExceeded):
        label = _OPERATION_LABELS.get(exc.operation, "операций")
        return (
            f"Бесплатный лимит {label} исчерпан. Скоро появится подписка — "
            "мы напишем, как только ее можно будет оформить."
        )
    if isinstance(exc, MonthlyCapExceeded):
        return (
            "Месячный лимит ИИ-операций семьи исчерпан — обновится 1-го числа "
            "следующего месяца. Подписка с расширенными лимитами уже готовится."
        )
    raise TypeError(f"denial_text: неизвестный тип исключения лимитов: {type(exc)!r}")
