"""Онбординг: превращает ответы опроса в текст профиля семьи через LLM."""
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core import repositories
from core.exceptions import LLMInvalidResponse, OnboardingLimitExceeded
from core.llm import LLMClient, load_prompt, parse_json_response

SLOT_LABELS = {"breakfast": "завтрак", "lunch": "обед", "dinner": "ужин"}


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


async def ensure_onboarding_attempt_allowed(
    session: AsyncSession, *, telegram_user_id: int, now: datetime | None = None
) -> None:
    """Проверить суточный лимит и записать попытку.

    Попытка пишется ДО вызова LLM: токены тратятся даже когда модель вернула
    невалидный JSON (generate_profile внутри делает retry), иначе обход лимита
    сводился бы к «вызывай так, чтобы падало».
    """
    now = now or datetime.now(UTC)
    limit = get_settings().onboarding_daily_limit
    used = await repositories.count_onboarding_attempts_today(
        session, telegram_user_id=telegram_user_id, now=now
    )
    if used >= limit:
        raise OnboardingLimitExceeded(limit)
    await repositories.log_onboarding_attempt(
        session, telegram_user_id=telegram_user_id
    )


def onboarding_denial_text(exc: OnboardingLimitExceeded) -> str:
    return (
        f"Сегодня уже {exc.limit} попыток составить профиль — это защита от "
        "перерасхода. Попробуйте завтра."
    )


@dataclass
class OnboardingAnswers:
    household: str
    slots: list[str]
    restrictions: list[str]
    cook_minutes: int
    preferences: list[str]
    extra: str | None
    city: str | None


@dataclass
class ProfileResult:
    profile_md: str
    timezone: str
    tokens_in: int
    tokens_out: int


def answers_to_prompt(answers: OnboardingAnswers) -> str:
    slots = ", ".join(SLOT_LABELS.get(s, s) for s in answers.slots)
    lines = [
        f"Состав семьи: {answers.household}",
        f"Планируемые приемы пищи: {slots}",
        f"Ограничения: {', '.join(answers.restrictions) or 'нет'}",
        f"Лимит активной готовки: {answers.cook_minutes} минут",
        f"Предпочтения: {', '.join(answers.preferences) or 'нет'}",
    ]
    if answers.extra:
        lines.append(f"Дополнительно: {answers.extra}")
    if answers.city:
        lines.append(f"Город: {answers.city}")
    return "\n".join(lines)


async def generate_profile(llm: LLMClient, answers: OnboardingAnswers) -> ProfileResult:
    system_blocks = [{"type": "text", "text": load_prompt("profile_generator")}]
    messages = [{"role": "user", "content": answers_to_prompt(answers)}]
    tokens_in = tokens_out = 0
    last_error: LLMInvalidResponse | None = None
    for _ in range(2):  # 1 попытка + 1 retry
        resp = await llm.chat(system_blocks=system_blocks, messages=messages)
        tokens_in += resp.tokens_in
        tokens_out += resp.tokens_out
        try:
            data = parse_json_response(resp.text)
            return ProfileResult(
                profile_md=str(data["profile_md"]),
                timezone=str(data.get("timezone") or "Europe/Moscow"),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        except (LLMInvalidResponse, KeyError) as e:
            last_error = e if isinstance(e, LLMInvalidResponse) else LLMInvalidResponse(str(e))
    raise last_error
