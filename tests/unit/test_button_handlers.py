"""Кнопки reply-клавиатуры маппятся на те же хэндлеры, что и команды."""
from unittest.mock import AsyncMock

from aiogram import F
from aiogram.filters import Command

from bot.handlers import family, menu, shopping
from bot.keyboards import BTN_ADD, BTN_FAMILY, BTN_TODAY


def _magic_repr(magic) -> str:
    """Структурное представление MagicFilter.

    aiogram/magic_filter не переопределяет __repr__: голый repr(magic_filter)
    отдает id объекта в памяти, поэтому две структурно одинаковые магии
    (например, две F.text == "...") никогда не совпадут строкой. Собираем
    репрезентацию из внутренних _operations (тоже __slots__-объекты без
    repr), где и лежит реальное сравнение (имя атрибута, компаратор, значение).
    """
    return repr(
        [
            (type(op).__name__, {s: getattr(op, s, None) for s in op.__slots__})
            for op in magic._operations
        ]
    )


def _registered_filters(router):
    """[(callback_name, [filter_reprs])] для всех message-хэндлеров роутера."""
    result = []
    for h in router.message.handlers:
        reprs = [
            _magic_repr(f.magic) if f.magic is not None else repr(f.callback)
            for f in h.filters
        ]
        result.append((h.callback.__name__, reprs))
    return result


def _has_text_binding(router, func_name: str, btn_text: str) -> bool:
    magic = _magic_repr(F.text == btn_text)
    return any(
        name == func_name and any(magic in f for f in filters)
        for name, filters in _registered_filters(router)
    )


def test_btn_today_bound_to_cmd_today():
    assert _has_text_binding(menu.router, "cmd_today", BTN_TODAY)


def test_btn_family_bound_to_both_family_views():
    assert _has_text_binding(family.router, "cmd_family", BTN_FAMILY)
    assert _has_text_binding(family.router, "cmd_family_member_view", BTN_FAMILY)


def test_btn_add_bound():
    assert _has_text_binding(shopping.router, "btn_add", BTN_ADD)


async def test_btn_add_asks_what_to_add():
    message = AsyncMock()
    await shopping.btn_add(message)
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == shopping._ADD_PROMPT
