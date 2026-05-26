from datetime import date
from unittest.mock import AsyncMock

from core.db import MealSlot
from core.llm import LLMResponse
from core.services import menu_planner
from core.services.family_service import get_or_create_family


async def test_start_planning_creates_draft_menu(db_session, monkeypatch):
    """LLM is mocked; service should parse JSON and save a draft menu."""
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)

    mock_llm_response = LLMResponse(
        text=(
            '{"meals": ['
            '{"date": "2026-05-26", "slot": "lunch", "dish_name": "Курица",'
            ' "side_dishes": ["рис"], "protein_kind": "chicken"},'
            '{"date": "2026-05-26", "slot": "dinner", "dish_name": "Лосось",'
            ' "side_dishes": ["брокколи"], "protein_kind": "fish"}'
            "]}"
        ),
        stop_reason="end_turn",
    )

    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(return_value=mock_llm_response)
    monkeypatch.setattr(menu_planner, "get_llm_client", lambda: fake_client)

    menu = await menu_planner.start_planning(
        db_session,
        family_id=family.id,
        days_count=1,
        start_date=date(2026, 5, 26),
        fridge_text="курица, рис",
    )

    assert menu.id is not None
    assert menu.days_count == 1
    assert menu.status.value == "draft"
    assert len(menu.meals) == 2
    slots = {m.slot for m in menu.meals}
    assert slots == {MealSlot.lunch, MealSlot.dinner}
