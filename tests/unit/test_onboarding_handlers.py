"""Хендлер-level тесты онбординга на моках (без aiogram-харнесса)."""
from unittest.mock import AsyncMock

from bot.handlers import onboarding as onb
from core.exceptions import LLMError


async def test_on_profile_ok_when_already_in_family_clears_state():
    """Юзер уже в семье (join по инвайту посреди онбординга) —
    «Всё верно» не должно создавать вторую семью."""
    cb = AsyncMock()
    state = AsyncMock()

    await onb.on_profile_ok(cb, state, db_session=None, family=object())

    state.clear.assert_awaited_once()
    cb.message.edit_text.assert_awaited_once()
    assert "уже состоите" in cb.message.edit_text.await_args.args[0]


async def test_generate_and_show_handles_llm_error(monkeypatch):
    """LLMError (таймаут/429/сеть) не должен вешать юзера на «Составляю профиль»."""

    async def boom(client, answers):
        raise LLMError("timeout")

    monkeypatch.setattr(onb, "generate_profile", boom)
    monkeypatch.setattr("core.services.onboarding.get_llm_client", lambda: object())

    message = AsyncMock()
    state = AsyncMock()
    state.get_data.return_value = {"household": "2 чел.", "slots": ["dinner"]}

    await onb._generate_and_show(message, state)

    state.clear.assert_awaited_once()
    placeholder = message.answer.return_value
    placeholder.edit_text.assert_awaited_once()
    assert "/start" in placeholder.edit_text.await_args.args[0]


async def test_on_profile_ok_creates_family_and_attaches_keyboard(monkeypatch):
    """После создания семьи финальное сообщение идет новым message
    с постоянной reply-клавиатурой (edit_text не умеет reply-клавиатуры)."""
    from types import SimpleNamespace

    from bot.keyboards import kb_main

    async def fake_create_family(db, **kwargs):
        return SimpleNamespace(id=1), None

    async def fake_log_llm_usage(db, **kwargs):
        return None

    monkeypatch.setattr(onb, "create_family", fake_create_family)
    monkeypatch.setattr(onb, "log_llm_usage", fake_log_llm_usage)

    cb = AsyncMock()
    state = AsyncMock()
    state.get_data.return_value = {
        "profile_md": "профиль",
        "timezone": "Europe/Moscow",
        "slots": ["dinner"],
    }

    await onb.on_profile_ok(cb, state, db_session=None, family=None)

    state.clear.assert_awaited_once()
    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    assert "Семья создана" in cb.message.answer.await_args.args[0]
    assert cb.message.answer.await_args.kwargs["reply_markup"] == kb_main()
