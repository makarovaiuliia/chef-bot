from datetime import date
from unittest.mock import AsyncMock

from core import repositories
from core.llm import LLMResponse
from core.services import conversation
from core.services.family_service import get_or_create_family


async def test_handle_message_no_tool_call(db_session, monkeypatch):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)

    fake_resp = LLMResponse(
        text="Привет! Чем помочь?",
        tool_calls=[],
        stop_reason="end_turn",
        tokens_in=100,
        tokens_out=10,
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr(conversation, "get_llm_client", lambda: fake_client)

    reply = await conversation.handle_message(
        db_session,
        family_id=family.id,
        telegram_user_id=111,
        text="Привет",
    )
    assert reply == "Привет! Чем помочь?"


async def test_handle_message_uses_tool(db_session, monkeypatch):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    menu = await repositories.create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=date(2026, 5, 26),
        days_count=1,
        meals=[
            {
                "date": date(2026, 5, 26),
                "slot": "lunch",
                "dish_name": "Курица",
                "side_dishes": ["рис"],
                "protein_kind": "chicken",
            }
        ],
    )
    await repositories.approve_menu(db_session, menu.id)

    tool_call_resp = LLMResponse(
        text="",
        tool_calls=[{"id": "t1", "name": "get_active_menu", "input": {}}],
        stop_reason="tool_use",
    )
    final_resp = LLMResponse(
        text="В меню: курица.",
        tool_calls=[],
        stop_reason="end_turn",
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(side_effect=[tool_call_resp, final_resp])
    monkeypatch.setattr(conversation, "get_llm_client", lambda: fake_client)

    reply = await conversation.handle_message(
        db_session,
        family_id=family.id,
        telegram_user_id=111,
        text="что в меню?",
    )
    assert "курица" in reply.lower()
    assert fake_client.chat.call_count == 2
