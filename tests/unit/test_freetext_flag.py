"""Free-text агент выключен фича-флагом: вместо LLM — подсказка с командами."""
from unittest.mock import AsyncMock

from bot.handlers import freetext


async def test_freetext_disabled_replies_command_hint(monkeypatch):
    monkeypatch.setattr(freetext, "_conversation_enabled", lambda: False)
    called = False

    async def fake_handle(*a, **kw):
        nonlocal called
        called = True

    monkeypatch.setattr(freetext.conversation, "handle_message", fake_handle)

    message = AsyncMock()
    state = AsyncMock()
    state.get_state.return_value = None

    await freetext.handle_free_text(
        message, state, family=object(), family_member=object(), db_session=None
    )

    assert called is False
    reply = message.answer.await_args.args[0]
    # ответ — подсказка со списком команд
    assert "/menu" in reply and "/help" in reply
