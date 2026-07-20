import json

import pytest

from core.exceptions import LLMInvalidResponse
from core.llm import LLMResponse
from core.services.onboarding import (
    OnboardingAnswers,
    answers_to_prompt,
    generate_profile,
)

ANSWERS = OnboardingAnswers(
    household="2 взрослых",
    slots=["lunch", "dinner"],
    restrictions=["без лука", "без глютена"],
    cook_minutes=40,
    preferences=["курица", "рыба"],
    extra="не любим кинзу",
    city="Бангкок",
)


class FakeLLM:
    def __init__(self, texts: list[str]):
        self._texts = list(texts)
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        return LLMResponse(text=self._texts.pop(0), tokens_in=10, tokens_out=20)


def test_answers_to_prompt_contains_all_answers():
    prompt = answers_to_prompt(ANSWERS)
    for chunk in ("2 взрослых", "без лука", "40", "курица", "кинзу", "Бангкок"):
        assert chunk in prompt


async def test_generate_profile_happy_path():
    ok = json.dumps({"profile_md": "# Профиль", "timezone": "Asia/Bangkok"})
    llm = FakeLLM([ok])
    result = await generate_profile(llm, ANSWERS)
    assert result.profile_md == "# Профиль"
    assert result.timezone == "Asia/Bangkok"
    assert result.tokens_in == 10


async def test_generate_profile_retries_once_on_bad_json():
    ok = json.dumps({"profile_md": "p", "timezone": "UTC"})
    llm = FakeLLM(["не json", ok])
    result = await generate_profile(llm, ANSWERS)
    assert llm.calls == 2
    assert result.profile_md == "p"


async def test_generate_profile_fails_after_two_bad():
    llm = FakeLLM(["мусор", "мусор"])
    with pytest.raises(LLMInvalidResponse):
        await generate_profile(llm, ANSWERS)
