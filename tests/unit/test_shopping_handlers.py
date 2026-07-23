"""Очистка списка: кнопка -> подтверждение -> очистка."""
from unittest.mock import AsyncMock

from bot.handlers import shopping as shopping_handler
from bot.keyboards import kb_shop_clear_confirm, kb_shopping_list


def _datas(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def test_clear_button_present_only_with_items():
    item = type("I", (), {"id": 1, "name": "Рис", "quantity": "", "bought": False})()
    assert "shop:clear" in _datas(kb_shopping_list([item]))
    assert "shop:clear" not in _datas(kb_shopping_list([]))


def test_clear_confirm_keyboard():
    assert _datas(kb_shop_clear_confirm()) == ["shop:clear:yes", "shop:clear:no"]


async def test_clear_yes_calls_service(monkeypatch):
    cleared = {}

    async def fake_clear(session, *, family_id):
        cleared["family_id"] = family_id
        return 5

    monkeypatch.setattr(shopping_handler.shopping_list, "clear_all_open", fake_clear)
    cb = AsyncMock()
    cb.data = "shop:clear:yes"
    family = type("F", (), {"id": 1})()

    await shopping_handler.cb_clear_yes(cb, family, db_session=None)

    assert cleared["family_id"] == 1
    assert "5" in cb.message.edit_text.await_args.args[0]
