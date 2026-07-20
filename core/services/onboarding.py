"""Онбординг: превращает ответы опроса в текст профиля семьи через LLM."""
from dataclasses import dataclass
from functools import lru_cache

from core.exceptions import LLMInvalidResponse
from core.llm import LLMClient, load_prompt, parse_json_response

SLOT_LABELS = {"breakfast": "завтрак", "lunch": "обед", "dinner": "ужин"}


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


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
                timezone=str(data.get("timezone") or "UTC"),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        except (LLMInvalidResponse, KeyError) as e:
            last_error = e if isinstance(e, LLMInvalidResponse) else LLMInvalidResponse(str(e))
    raise last_error
